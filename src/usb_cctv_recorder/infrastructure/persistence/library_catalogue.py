"""SQLite-backed browse catalogue reconstructed from immutable media evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from usb_cctv_recorder.application.dto import LibraryDetails, LibraryFilter, LibraryItem
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import FfprobeVerifier, MediaVerificationError
from usb_cctv_recorder.infrastructure.storage.checksums import Sha256Service

from .manifest import ManifestStore, SessionManifest
from .sqlite import SQLiteCatalogue


class LibraryItemNotFoundError(ValueError):
    """The requested catalogue record does not exist or is not actionable."""


class SQLiteLibraryCatalogue:
    """Owns catalogue writes; rebuilds never alter evidence bytes or manifests."""

    def __init__(
        self,
        catalogue: SQLiteCatalogue,
        *,
        manifests: ManifestStore | None = None,
        verifier: FfprobeVerifier | None = None,
        checksums: Sha256Service | None = None,
    ) -> None:
        self._catalogue = catalogue
        self._catalogue.migrate()
        self._manifests = manifests or ManifestStore()
        self._verifier = verifier or FfprobeVerifier()
        self._checksums = checksums or Sha256Service()
        self._lock = RLock()

    def rebuild(self, media_root: Path) -> int:
        """Replace derived browse records while preserving durable protection choices."""
        with self._lock:
            protected_paths = {
                str(row[0]): bool(row[1])
                for row in self._catalogue.connection.execute(
                    "SELECT file_path, protected FROM segments WHERE protected = 1"
                )
            }
            with self._catalogue.transaction():
                self._catalogue.connection.execute("DELETE FROM recording_gaps")
                self._catalogue.connection.execute("DELETE FROM segments")
                self._catalogue.connection.execute("DELETE FROM sessions")
                if not media_root.is_dir():
                    return 0
                count = self._rebuild_originals(media_root, protected_paths)
                count += self._rebuild_quarantine(media_root, protected_paths)
                count += self._rebuild_archives(media_root, protected_paths)
            return count

    def count(self, filters: LibraryFilter) -> int:
        with self._lock:
            sql, values = self._item_query(filters, count=True)
            row = self._catalogue.connection.execute(sql, values).fetchone()
            assert row is not None
            return int(row[0])

    def page(self, filters: LibraryFilter, offset: int, limit: int) -> tuple[LibraryItem, ...]:
        with self._lock:
            sql, values = self._item_query(filters, count=False)
            rows = self._catalogue.connection.execute(sql, (*values, limit, offset)).fetchall()
            return tuple(self._to_item(row) for row in rows)

    def details(self, item_id: str) -> LibraryDetails:
        with self._lock:
            item = self._find_item(item_id)
            if item.kind == "gap":
                row = self._catalogue.connection.execute(
                    """SELECT reason, ended_at, attempts, last_good_video_monotonic,
                             last_good_audio_monotonic FROM recording_gaps WHERE id = ?""",
                    (item_id,),
                ).fetchone()
                if row is None:
                    raise LibraryItemNotFoundError("gap no longer exists")
                facts: tuple[tuple[str, str], ...] = (
                    ("Reason", str(row[0])),
                    ("Ended", str(row[1] or "ongoing")),
                    ("Recovery attempts", str(row[2])),
                    (
                        "Last good video monotonic",
                        str(row[3] if row[3] is not None else "unknown"),
                    ),
                    (
                        "Last good audio monotonic",
                        str(row[4] if row[4] is not None else "unknown"),
                    ),
                )
                return LibraryDetails(item, facts)
            facts = (
                ("Path", item.file_path or "missing path"),
                ("Validation", item.validation_state),
                ("Segment state", item.segment_state or "unknown"),
                ("Diagnostic", item.error_state or "none"),
            )
            return LibraryDetails(item, facts)

    def set_protected(self, item_id: str, protected: bool) -> LibraryItem:
        with self._lock:
            item = self._find_item(item_id)
            if item.kind != "media":
                raise LibraryItemNotFoundError("gaps cannot be protected")
            with self._catalogue.transaction():
                cursor = self._catalogue.connection.execute(
                    "UPDATE segments SET protected = ?, updated_at = ? WHERE id = ?",
                    (int(protected), _now(), item_id),
                )
                if cursor.rowcount != 1:
                    raise LibraryItemNotFoundError("media item no longer exists")
            return self._find_item(item_id)

    def reverify(self, item_id: str) -> LibraryItem:
        with self._lock:
            item = self._find_item(item_id)
            if item.kind != "media" or item.file_path is None:
                raise LibraryItemNotFoundError("only media can be re-verified")
            path = Path(item.file_path)
            error: str | None = None
            valid = False
            if not path.is_file():
                error = "missing_file"
            else:
                row = self._catalogue.connection.execute(
                    "SELECT sha256 FROM segments WHERE id = ?", (item_id,)
                ).fetchone()
                try:
                    actual = self._checksums.digest_file(path)
                    if row is not None and row[0] and actual != row[0]:
                        error = "checksum_mismatch"
                    else:
                        self._verifier.verify(path, expect_video=False, expect_audio=False)
                        valid = True
                except (MediaVerificationError, OSError) as verification_error:
                    error = f"verification_failed: {verification_error}"
            with self._catalogue.transaction():
                self._catalogue.connection.execute(
                    """UPDATE segments SET streams_validated = ?, error_state = ?, updated_at = ?
                       WHERE id = ?""",
                    (int(valid), error, _now(), item_id),
                )
            return self._find_item(item_id)

    def _rebuild_originals(self, root: Path, protected_paths: dict[str, bool]) -> int:
        count = 0
        originals = root / "originals"
        if not originals.is_dir():
            return count
        for manifest_path in sorted(originals.rglob("session.json")):
            try:
                manifest = self._manifests.load(manifest_path)
            except (OSError, ValueError):
                continue
            self._insert_session(manifest)
            event_facts = _event_facts(manifest_path.parent / "events.jsonl")
            expected_names: set[str] = set()
            for segment in manifest.segments:
                expected_names.add(segment.filename)
                path = manifest_path.parent / segment.filename
                error = None if path.is_file() else "missing_file"
                self._insert_segment(
                    segment.segment_id,
                    str(manifest.session_id),
                    (
                        "interrupted_verified"
                        if segment.filename in event_facts.interrupted
                        else "verified"
                    ),
                    "original",
                    path,
                    manifest.created_at.isoformat(),
                    segment.duration_seconds,
                    segment.sha256,
                    path.stat().st_size if path.is_file() else None,
                    error,
                    protected_paths,
                )
                count += 1
            for path in sorted(manifest_path.parent.glob("*.mkv")):
                if path.name not in expected_names:
                    self._insert_segment(
                        _derived_id("unmanifested", path),
                        str(manifest.session_id),
                        "interrupted_unverified",
                        "original",
                        path,
                        manifest.updated_at.isoformat(),
                        None,
                        None,
                        path.stat().st_size,
                        "unmanifested_media",
                        protected_paths,
                    )
                    count += 1
            self._insert_gaps(str(manifest.session_id), manifest_path.parent / "recovery.json")
        return count

    def _rebuild_quarantine(self, root: Path, protected_paths: dict[str, bool]) -> int:
        quarantine = root / "quarantine"
        if not quarantine.is_dir():
            return 0
        count = 0
        for path in sorted(quarantine.rglob("*.mkv")):
            session_id = f"quarantine:{path.parent.name}"
            self._insert_session_values(session_id, "failed", _now())
            self._insert_segment(
                _derived_id("quarantine", path),
                session_id,
                "quarantined",
                "quarantine",
                path,
                _now(),
                None,
                None,
                path.stat().st_size,
                "interrupted media failed verification; quarantined",
                protected_paths,
            )
            count += 1
        return count

    def _rebuild_archives(self, root: Path, protected_paths: dict[str, bool]) -> int:
        archives = root / "archives"
        if not archives.is_dir():
            return 0
        count = 0
        for path in sorted(archives.rglob("*.mkv")):
            session_id = f"archive:{_derived_id('session', path.parent)}"
            self._insert_session_values(session_id, "completed", _now())
            self._insert_segment(
                _derived_id("archive", path),
                session_id,
                "archived_verified",
                "archive",
                path,
                _now(),
                None,
                None,
                path.stat().st_size,
                None,
                protected_paths,
            )
            count += 1
        return count

    def _insert_session(self, manifest: SessionManifest) -> None:
        self._insert_session_values(
            str(manifest.session_id), manifest.state.value, manifest.created_at.isoformat()
        )

    def _insert_session_values(self, session_id: str, state: str, timestamp: str) -> None:
        self._catalogue.connection.execute(
            "INSERT OR IGNORE INTO sessions(id, state, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, state, timestamp, timestamp),
        )

    def _insert_segment(
        self,
        item_id: str,
        session_id: str,
        state: str,
        media_class: str,
        path: Path,
        started_at: str,
        duration: float | None,
        checksum: str | None,
        size: int | None,
        error: str | None,
        protected_paths: dict[str, bool],
    ) -> None:
        self._catalogue.connection.execute(
            """INSERT INTO segments(
                id, session_id, state, media_class, file_path, started_at,
                monotonic_duration_seconds, streams_validated, file_size_bytes, sha256,
                protected, error_state, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id,
                session_id,
                state,
                media_class,
                str(path),
                started_at,
                duration,
                int(error is None and checksum is not None),
                size,
                checksum,
                int(protected_paths.get(str(path), False)),
                error,
                _now(),
                _now(),
            ),
        )

    def _insert_gaps(self, session_id: str, recovery_path: Path) -> None:
        try:
            document = json.loads(recovery_path.read_text(encoding="utf-8"))
            gaps = document.get("gaps", [])
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(gaps, list):
            return
        inserted = False
        for index, gap in enumerate(gaps):
            if not isinstance(gap, dict) or not isinstance(gap.get("started_at"), str):
                continue
            self._catalogue.connection.execute(
                """INSERT INTO recording_gaps(
                    id, session_id, reason, started_at, ended_at, duration_seconds, attempts,
                    last_good_video_monotonic, last_good_audio_monotonic
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"gap:{session_id}:{index}",
                    session_id,
                    str(gap.get("reason", "unknown")),
                    gap["started_at"],
                    gap.get("ended_at") if isinstance(gap.get("ended_at"), str) else None,
                    _optional_float(gap.get("duration_seconds")),
                    int(gap.get("attempts", 0)),
                    _optional_float(gap.get("last_good_video_monotonic")),
                    _optional_float(gap.get("last_good_audio_monotonic")),
                ),
            )
            inserted = True
        if inserted:
            self._catalogue.connection.execute(
                "UPDATE segments SET has_recording_gap = 1 WHERE session_id = ?", (session_id,)
            )

    def _find_item(self, item_id: str) -> LibraryItem:
        sql, values = self._item_query(LibraryFilter())
        row = self._catalogue.connection.execute(
            f"SELECT * FROM ({sql.removesuffix(' LIMIT ? OFFSET ?')}) WHERE item_id = ?",  # noqa: S608
            (*values, item_id),
        ).fetchone()
        if row is None:
            raise LibraryItemNotFoundError("catalogue item does not exist")
        return self._to_item(row)

    def _item_query(
        self, filters: LibraryFilter, *, count: bool = False
    ) -> tuple[str, tuple[object, ...]]:
        query = """
            SELECT id AS item_id, 'media' AS kind, session_id, media_class, file_path,
                   started_at, monotonic_duration_seconds AS duration_seconds, protected,
                   CASE WHEN error_state IS NOT NULL THEN 'diagnostic'
                        WHEN streams_validated = 1 THEN 'verified'
                        ELSE 'unverified' END AS validation_state,
                   CASE WHEN has_recording_gap = 1 THEN 'has_gap' ELSE 'none' END AS gap_state,
                   state AS segment_state, error_state
            FROM segments
            UNION ALL
            SELECT id AS item_id, 'gap' AS kind, session_id, 'gap' AS media_class,
                   NULL AS file_path, started_at, duration_seconds, 0 AS protected,
                   'not_applicable' AS validation_state,
                   'gap' AS gap_state, NULL AS segment_state, reason AS error_state
            FROM recording_gaps
        """
        clauses: list[str] = []
        values: list[object] = []
        if filters.date:
            clauses.append("started_at LIKE ?")
            values.append(f"{filters.date}%")
        if filters.session_id:
            clauses.append("session_id = ?")
            values.append(filters.session_id)
        if filters.media_class:
            clauses.append("media_class = ?")
            values.append(filters.media_class)
        if filters.protected is not None:
            clauses.append("protected = ?")
            values.append(int(filters.protected))
        if filters.validation_state:
            clauses.append("validation_state = ?")
            values.append(filters.validation_state)
        if filters.gap_state:
            clauses.append("gap_state = ?")
            values.append(filters.gap_state)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        if count:
            return f"SELECT COUNT(*) FROM ({query}){where}", tuple(values)
        return (
            f"SELECT * FROM ({query}){where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
            tuple(values),
        )

    @staticmethod
    def _to_item(row: tuple[object, ...]) -> LibraryItem:
        return LibraryItem(
            item_id=str(row[0]),
            kind=str(row[1]),
            session_id=str(row[2]),
            media_class=str(row[3]),
            file_path=str(row[4]) if row[4] is not None else None,
            started_at=str(row[5]),
            duration_seconds=_optional_float(row[6]),
            protected=bool(row[7]),
            validation_state=str(row[8]),
            gap_state=str(row[9]),
            segment_state=str(row[10]) if row[10] is not None else None,
            error_state=str(row[11]) if row[11] is not None else None,
        )


class _EventFacts:
    def __init__(self) -> None:
        self.interrupted: set[str] = set()


def _event_facts(path: Path) -> _EventFacts:
    facts = _EventFacts()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return facts
    for line in lines:
        try:
            event = json.loads(line)
            payload = event.get("payload", {})
            if event.get("event_type") == "segment_interrupted_verified" and isinstance(
                payload, dict
            ):
                filename = payload.get("filename")
                if isinstance(filename, str):
                    facts.interrupted.add(filename)
        except json.JSONDecodeError:
            continue
    return facts


def _derived_id(prefix: str, path: Path) -> str:
    return f"{prefix}:{hashlib.sha256(str(path).encode()).hexdigest()[:24]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _optional_float(value: object) -> float | None:
    if isinstance(value, float):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return None
