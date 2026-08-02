"""Run the Phase 10 controlled storage-pressure acceptance check on a disposable directory."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from usb_cctv_recorder.application.dto import ArchiveJobView
from usb_cctv_recorder.application.storage import StoragePolicy
from usb_cctv_recorder.infrastructure.persistence.library_catalogue import SQLiteLibraryCatalogue
from usb_cctv_recorder.infrastructure.persistence.sqlite import SQLiteCatalogue
from usb_cctv_recorder.infrastructure.storage.governor import FilesystemStorageGovernor


class _ArchiveBoundary:
    """Records archive queueing; this check deliberately never runs a transcode."""

    def __init__(self) -> None:
        self.recovery_calls = 0
        self.queued = 0

    def recover_partials(self) -> tuple[object, ...]:
        self.recovery_calls += 1
        return ()

    def enqueue(self, request: object) -> tuple[ArchiveJobView, ...]:
        self.queued += len(getattr(request, "source_item_ids", ()))
        return ()


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-directory",
        required=True,
        type=Path,
        help="Existing empty-test-capable directory; a new phase10-acceptance-* child is created.",
    )
    parsed = parser.parse_args(arguments)
    base = parsed.base_directory.expanduser().resolve()
    if not base.is_absolute() or not base.is_dir():
        raise ValueError("--base-directory must be an existing absolute directory")
    root = (
        base
        / f"phase10-acceptance-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    )
    root.mkdir(mode=0o700)
    state = root / "state"
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(state / "catalogue.sqlite"))
    archive = _ArchiveBoundary()
    governor = FilesystemStorageGovernor(
        root,
        catalogue,
        archive,  # type: ignore[arg-type]
        StoragePolicy(
            configured_cap_bytes=20_000_000,
            operating_system_reserve_bytes=0,
            emergency_finalization_reserve_bytes=0,
            planned_session_hours=1,
        ),
    )
    share = _insert_media(catalogue, root, "share", "share_copy", 4_000_000)
    archive_path = _insert_media(catalogue, root, "archive", "archive", 5_000_000)
    protected = _insert_media(catalogue, root, "protected", "archive", 2_000_000, protected=True)
    unverified = _insert_media(
        catalogue, root, "unverified", "archive", 2_000_000, state="interrupted_unverified"
    )
    current = _insert_media(catalogue, root, "current", "original", 2_000_000, state="recording")
    quarantined = _insert_media(catalogue, root, "quarantined", "quarantine", 2_000_000)

    reclaimed = governor.free_bytes(8_000_000, recording_active=True)
    filler = root / "metadata-pressure.bin"
    filler.write_bytes(b"x" * 12_000_000)
    critical = governor.ensure_working_reserve(3_000_000, recording_active=True)
    report = {
        "schema_version": 1,
        "root": str(root),
        "actual_usage_bytes": governor.dashboard().usage.total_bytes,
        "effective_cap_bytes": governor.dashboard().effective_cap_bytes,
        "reclaimed_actions": [action.action for action in reclaimed.actions],
        "reclaimed_bytes": sum(action.bytes_affected for action in reclaimed.actions),
        "archive_recovery_analysis_calls": archive.recovery_calls,
        "critical_safe_stop_required": critical.safe_stop_required,
        "preserved": {
            "protected": protected.exists(),
            "unverified": unverified.exists(),
            "current": current.exists(),
            "quarantined": quarantined.exists(),
        },
        "deleted": {"share_copy": not share.exists(), "archive": not archive_path.exists()},
        "audit_path": str(root / ".storage-audit.jsonl"),
        "audit_exists": (root / ".storage-audit.jsonl").is_file(),
        "result": "pass"
        if (
            [action.action for action in reclaimed.actions[:2]]
            == ["deleted_share_copy", "deleted_archive"]
            and critical.safe_stop_required
            and all(
                (protected.exists(), unverified.exists(), current.exists(), quarantined.exists())
            )
            and not share.exists()
            and not archive_path.exists()
        )
        else "fail",
    }
    report_path = root / "phase-10-storage-acceptance.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Report saved to {report_path}")
    return 0 if report["result"] == "pass" else 1


def _insert_media(
    catalogue: SQLiteLibraryCatalogue,
    root: Path,
    item_id: str,
    media_class: str,
    size: int,
    *,
    protected: bool = False,
    state: str = "archived_verified",
) -> Path:
    directory = {
        "original": "originals",
        "archive": "archives",
        "share_copy": "share-copies",
        "quarantine": "quarantine",
    }[media_class]
    path = root / directory / f"{item_id}.mkv"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    now = datetime.now(UTC).isoformat()
    connection = catalogue._catalogue.connection
    with catalogue._catalogue.transaction():
        connection.execute(
            "INSERT OR IGNORE INTO sessions(id, state, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("acceptance", "completed", now, now),
        )
        connection.execute(
            """INSERT INTO segments(
                id, session_id, state, media_class, file_path, started_at,
                monotonic_duration_seconds, streams_validated, file_size_bytes, sha256,
                protected, created_at, updated_at
            ) VALUES (?, 'acceptance', ?, ?, ?, ?, 3600, 1, ?, 'acceptance', ?, ?, ?)""",
            (item_id, state, media_class, str(path), now, size, int(protected), now, now),
        )
    return path


if __name__ == "__main__":
    sys.exit(main())
