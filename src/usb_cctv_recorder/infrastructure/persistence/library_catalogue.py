"""SQLite-backed browse catalogue reconstructed from immutable media evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from usb_cctv_recorder.application.dto import (
    ArchiveJobStateView,
    ArchiveJobView,
    ArchiveProfileKind,
    LibraryDetails,
    LibraryFilter,
    LibraryItem,
)
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
                archived_sources = self._archive_source_ids(media_root)
                count = self._rebuild_originals(media_root, protected_paths, archived_sources)
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

    def archive_source(self, item_id: str) -> LibraryItem:
        """Return an eligible original; callers still revalidate it immediately before use."""
        with self._lock:
            item = self._find_item(item_id)
            if (
                item.kind != "media"
                or item.media_class != "original"
                or item.protected
                or item.validation_state != "verified"
                or item.segment_state not in {"verified", "interrupted_verified"}
                or item.file_path is None
            ):
                raise LibraryItemNotFoundError("media is ineligible for archiving")
            return item

    def eligible_original_ids(
        self, *, session_id: str | None = None, requested_bytes: int | None = None
    ) -> tuple[str, ...]:
        """Return only stable, verified, unprotected originals for explicit manual selection."""
        if requested_bytes is not None and requested_bytes <= 0:
            raise ValueError("requested free space must be positive")
        with self._lock:
            clauses = [
                "media_class = 'original'",
                "state IN ('verified', 'interrupted_verified')",
                "protected = 0",
                "streams_validated = 1",
                "error_state IS NULL",
            ]
            values: list[object] = []
            if session_id:
                clauses.append("session_id = ?")
                values.append(session_id)
            rows = self._catalogue.connection.execute(
                f"SELECT id, file_size_bytes FROM segments WHERE {' AND '.join(clauses)} "  # noqa: S608
                "ORDER BY started_at, id",
                values,
            ).fetchall()
            selected: list[str] = []
            recovered = 0
            for item_id, size in rows:
                selected.append(str(item_id))
                recovered += int(size) if isinstance(size, int) else 0
                if requested_bytes is not None and recovered >= requested_bytes:
                    break
            return tuple(selected)

    def create_archive_job(
        self,
        job_id: str,
        source: LibraryItem,
        destination: Path,
        work_path: Path,
        profile: ArchiveProfileKind,
        delete_source_after_commit: bool,
    ) -> ArchiveJobView:
        with self._lock, self._catalogue.transaction():
            now = _now()
            self._catalogue.connection.execute(
                """INSERT INTO archive_jobs(
                    id, segment_id, state, created_at, updated_at, source_path, destination_path,
                    work_path, profile, delete_source_after_commit, progress_percent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    job_id,
                    source.item_id,
                    ArchiveJobStateView.QUEUED.value,
                    now,
                    now,
                    source.file_path,
                    str(destination),
                    str(work_path),
                    profile.value,
                    int(delete_source_after_commit),
                ),
            )
            self._catalogue.connection.execute(
                "UPDATE segments SET state = ?, updated_at = ? WHERE id = ?",
                ("archive_queued", now, source.item_id),
            )
        return self.archive_job(job_id)

    def archive_job(self, job_id: str) -> ArchiveJobView:
        with self._lock:
            row = self._catalogue.connection.execute(
                """SELECT id, segment_id, source_path, destination_path, profile, state,
                          delete_source_after_commit, progress_percent, failure_code, failure_detail
                   FROM archive_jobs WHERE id = ?""",
                (job_id,),
            ).fetchone()
            if row is None:
                raise LibraryItemNotFoundError("archive job does not exist")
            return _to_archive_job(row)

    def archive_jobs(self) -> tuple[ArchiveJobView, ...]:
        with self._lock:
            rows = self._catalogue.connection.execute(
                """SELECT id, segment_id, source_path, destination_path, profile, state,
                          delete_source_after_commit, progress_percent, failure_code, failure_detail
                   FROM archive_jobs ORDER BY created_at, id"""
            ).fetchall()
            return tuple(_to_archive_job(row) for row in rows)

    def archive_job_source(self, job_id: str) -> LibraryItem:
        with self._lock:
            row = self._catalogue.connection.execute(
                "SELECT segment_id FROM archive_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise LibraryItemNotFoundError("archive job does not exist")
            item = self._find_item(str(row[0]))
            if item.file_path is None or item.protected or item.media_class != "original":
                raise LibraryItemNotFoundError("archive source is no longer eligible")
            return item

    def update_archive_job(
        self,
        job_id: str,
        state: ArchiveJobStateView,
        *,
        progress_percent: int | None = None,
        failure_code: str | None = None,
        failure_detail: str | None = None,
        restore_source_state: bool = False,
    ) -> ArchiveJobView:
        if not 0 <= (progress_percent if progress_percent is not None else 0) <= 100:
            raise ValueError("archive progress must be between 0 and 100")
        with self._lock, self._catalogue.transaction():
            row = self._catalogue.connection.execute(
                "SELECT segment_id FROM archive_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise LibraryItemNotFoundError("archive job does not exist")
            values: list[object] = [state.value, _now(), failure_code, failure_detail]
            assignment = "state = ?, updated_at = ?, failure_code = ?, failure_detail = ?"
            if progress_percent is not None:
                assignment += ", progress_percent = ?"
                values.append(progress_percent)
            values.append(job_id)
            self._catalogue.connection.execute(
                f"UPDATE archive_jobs SET {assignment} WHERE id = ?",
                values,  # noqa: S608
            )
            if restore_source_state:
                self._catalogue.connection.execute(
                    """UPDATE segments SET state = CASE WHEN state = 'archive_queued' OR state =
                       'archiving' OR state = 'archive_validating' THEN 'verified' ELSE state END,
                       updated_at = ? WHERE id = ?""",
                    (_now(), row[0]),
                )
        return self.archive_job(job_id)

    def commit_archive(
        self,
        job_id: str,
        *,
        archive_id: str,
        checksum: str,
        size: int,
        duration_seconds: float,
        video_codec: str | None,
        audio_codec: str | None,
        delete_source: bool,
    ) -> ArchiveJobView:
        """Commit only already-published, fully decoded archive media."""
        with self._lock, self._catalogue.transaction():
            job = self._catalogue.connection.execute(
                """SELECT segment_id, destination_path FROM archive_jobs WHERE id = ?""", (job_id,)
            ).fetchone()
            if job is None:
                raise LibraryItemNotFoundError("archive job does not exist")
            source = self._catalogue.connection.execute(
                "SELECT session_id, started_at FROM segments WHERE id = ?", (job[0],)
            ).fetchone()
            if source is None:
                raise LibraryItemNotFoundError("archive source does not exist")
            now = _now()
            self._catalogue.connection.execute(
                """INSERT INTO segments(
                    id, session_id, state, media_class, file_path, started_at,
                    monotonic_duration_seconds, video_codec, audio_codec, streams_validated,
                    file_size_bytes, sha256, archive_source_segment_id, created_at, updated_at,
                    archived_at
                ) VALUES (
                    ?, ?, 'archived_verified', 'archive', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?
                )""",
                (
                    archive_id,
                    source[0],
                    job[1],
                    source[1],
                    duration_seconds,
                    video_codec,
                    audio_codec,
                    size,
                    checksum,
                    job[0],
                    now,
                    now,
                    now,
                ),
            )
            self._catalogue.connection.execute(
                """UPDATE archive_jobs SET state = 'committed', progress_percent = 100,
                   updated_at = ?, failure_code = NULL, failure_detail = NULL WHERE id = ?""",
                (now, job_id),
            )
            if delete_source:
                self._catalogue.connection.execute(
                    """UPDATE segments SET state = 'deleted', deleted_at = ?, updated_at = ?
                       WHERE id = ?""",
                    (now, now, job[0]),
                )
        return self.archive_job(job_id)

    def mark_source_deleted(self, job_id: str) -> None:
        """Record a post-commit source deletion; callers must fsync the directory first."""
        with self._lock, self._catalogue.transaction():
            row = self._catalogue.connection.execute(
                "SELECT segment_id FROM archive_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise LibraryItemNotFoundError("archive job does not exist")
            self._catalogue.connection.execute(
                """UPDATE segments SET state = 'deleted', deleted_at = ?, updated_at = ?
                   WHERE id = ?""",
                (_now(), _now(), row[0]),
            )

    def add_derived_copy(
        self, source: LibraryItem, destination: Path, checksum: str
    ) -> LibraryItem:
        with self._lock, self._catalogue.transaction():
            item_id = f"share:{uuid4()}"
            now = _now()
            self._catalogue.connection.execute(
                """INSERT INTO segments(
                    id, session_id, state, media_class, file_path, started_at,
                    monotonic_duration_seconds, streams_validated, file_size_bytes, sha256,
                    archive_source_segment_id, created_at, updated_at
                ) VALUES (?, ?, 'archived_verified', 'share_copy', ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    source.session_id,
                    str(destination),
                    source.started_at,
                    source.duration_seconds,
                    destination.stat().st_size,
                    checksum,
                    source.item_id,
                    now,
                    now,
                ),
            )
        return self._find_item(item_id)

    def relocate_archive(self, item_id: str, destination: Path) -> LibraryItem:
        with self._lock, self._catalogue.transaction():
            item = self._find_item(item_id)
            if item.media_class != "archive" or item.file_path is None:
                raise LibraryItemNotFoundError("only archives can move to the active library")
            self._catalogue.connection.execute(
                "UPDATE segments SET file_path = ?, moved_at = ?, updated_at = ? WHERE id = ?",
                (str(destination), _now(), _now(), item_id),
            )
        return self._find_item(item_id)

    def _rebuild_originals(
        self, root: Path, protected_paths: dict[str, bool], archived_sources: set[str]
    ) -> int:
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
                        "deleted"
                        if not path.is_file() and segment.segment_id in archived_sources
                        else "interrupted_verified"
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
            manifest = _archive_manifest(path)
            source_id = manifest.get("source_segment_id") if manifest else None
            session_id = (
                _session_for_source(self._catalogue.connection, source_id)
                if isinstance(source_id, str)
                else None
            ) or f"archive:{_derived_id('session', path.parent)}"
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
                archive_source_segment_id=source_id if isinstance(source_id, str) else None,
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
        archive_source_segment_id: str | None = None,
    ) -> None:
        self._catalogue.connection.execute(
            """INSERT INTO segments(
                id, session_id, state, media_class, file_path, started_at,
                monotonic_duration_seconds, streams_validated, file_size_bytes, sha256,
                protected, error_state, created_at, updated_at, archive_source_segment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                archive_source_segment_id,
            ),
        )

    @staticmethod
    def _archive_source_ids(root: Path) -> set[str]:
        archives = root / "archives"
        if not archives.is_dir():
            return set()
        return {
            str(source_id)
            for path in archives.rglob("*.archive-manifest.json")
            if (document := _archive_manifest_path(path)) is not None
            and isinstance(source_id := document.get("source_segment_id"), str)
        }

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
            FROM segments WHERE state != 'deleted'
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


def _archive_manifest(path: Path) -> dict[str, object]:
    return _archive_manifest_path(path.with_suffix(".archive-manifest.json")) or {}


def _archive_manifest_path(path: Path) -> dict[str, object] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _session_for_source(connection: sqlite3.Connection, source_id: object) -> str | None:
    if not isinstance(source_id, str):
        return None
    row = connection.execute(
        "SELECT session_id FROM segments WHERE id = ?", (source_id,)
    ).fetchone()
    return str(row[0]) if row is not None else None


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


def _to_archive_job(row: tuple[object, ...]) -> ArchiveJobView:
    try:
        profile = ArchiveProfileKind(str(row[4]))
        state = ArchiveJobStateView(str(row[5]))
    except ValueError as error:
        raise LibraryItemNotFoundError("archive job has an invalid durable state") from error
    return ArchiveJobView(
        job_id=str(row[0]),
        source_item_id=str(row[1]),
        source_path=str(row[2] or ""),
        destination_path=str(row[3] or ""),
        profile=profile,
        state=state,
        delete_source_after_commit=bool(row[6]),
        progress_percent=int(row[7]) if isinstance(row[7], int | str | bytes | bytearray) else 0,
        failure_code=str(row[8]) if row[8] is not None else None,
        failure_detail=str(row[9]) if row[9] is not None else None,
    )
