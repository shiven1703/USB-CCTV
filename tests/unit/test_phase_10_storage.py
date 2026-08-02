"""Phase 10 storage-policy, retention ordering, and safe-stop coverage."""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from usb_cctv_recorder.application.dto import (
    ArchiveJobStateView,
    ArchiveJobView,
    ArchiveProfileKind,
    LibraryFilter,
)
from usb_cctv_recorder.application.storage import (
    StorageAction,
    StorageDashboard,
    StorageDecision,
    StorageGovernorService,
    StoragePolicy,
    StorageUsage,
)
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request
from usb_cctv_recorder.infrastructure.persistence.library_catalogue import SQLiteLibraryCatalogue
from usb_cctv_recorder.infrastructure.persistence.sqlite import SQLiteCatalogue
from usb_cctv_recorder.infrastructure.storage.governor import FilesystemStorageGovernor
from usb_cctv_recorder.worker.supervisor import WorkerSupervisor


def _disk_usage(free: int):
    return lambda _path: shutil._ntuple_diskusage(200_000_000_000, 0, free)


class _Archive:
    def __init__(self) -> None:
        self.recovered = 0
        self.requests: list[object] = []

    def recover_partials(self) -> tuple[object, ...]:
        self.recovered += 1
        return ()

    def enqueue(self, request: object) -> tuple[ArchiveJobView, ...]:
        self.requests.append(request)
        return (
            ArchiveJobView(
                "job-1",
                "original-1",
                "/source.mkv",
                "/archive.mkv",
                ArchiveProfileKind.COMPRESSED,
                ArchiveJobStateView.QUEUED,
                False,
                0,
                None,
                None,
            ),
        )


def _catalogue(root: Path) -> SQLiteLibraryCatalogue:
    return SQLiteLibraryCatalogue(
        SQLiteCatalogue(root.parent / f"{root.name}-state" / "catalogue.sqlite")
    )


def _media(
    catalogue: SQLiteLibraryCatalogue,
    root: Path,
    item_id: str,
    media_class: str,
    *,
    protected: bool = False,
    state: str = "archived_verified",
    bytes_: int = 10,
) -> Path:
    relative = {
        "original": Path("originals") / f"{item_id}.mkv",
        "archive": Path("archives") / f"{item_id}.mkv",
        "share_copy": Path("share_copies") / f"{item_id}.mkv",
        "quarantine": Path("quarantine") / f"{item_id}.mkv",
    }[media_class]
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * bytes_)
    now = datetime(2026, 8, 2, tzinfo=UTC).isoformat()
    connection = catalogue._catalogue.connection
    with catalogue._catalogue.transaction():
        connection.execute(
            "INSERT OR IGNORE INTO sessions(id, state, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("session", "completed", now, now),
        )
        connection.execute(
            """INSERT INTO segments(
                id, session_id, state, media_class, file_path, started_at,
                monotonic_duration_seconds, streams_validated, file_size_bytes, sha256,
                protected, created_at, updated_at
            ) VALUES (?, 'session', ?, ?, ?, ?, 3600, 1, ?, 'a', ?, ?, ?)""",
            (item_id, state, media_class, str(path), now, bytes_, int(protected), now, now),
        )
    return path


def _governor(
    root: Path, free: int = 100_000_000_000
) -> tuple[FilesystemStorageGovernor, _Archive]:
    archive = _Archive()
    return (
        FilesystemStorageGovernor(root, _catalogue(root), archive, disk_usage=_disk_usage(free)),  # type: ignore[arg-type]
        archive,
    )


def test_exact_cap_reserves_and_default_pool_ratios(tmp_path: Path) -> None:
    governor, _ = _governor(tmp_path, 104_200_000_000)
    dashboard = governor.dashboard()

    assert dashboard.effective_cap_bytes == 76_200_000_000
    assert dashboard.original_pool_bytes == 39_624_000_000
    assert dashboard.archive_pool_bytes == 25_146_000_000
    assert dashboard.metadata_pool_bytes == 3_810_000_000
    assert dashboard.transaction_headroom_bytes == 7_620_000_000
    assert dashboard.estimated_next_session_bytes == 13_200_000_000
    assert dashboard.estimated_three_night_original_bytes == 39_600_000_000
    assert dashboard.estimated_seven_night_history_bytes == 92_400_000_000


def test_effective_cap_uses_free_space_clamps_to_zero_and_rejects_over_90gb(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="90,000,000,000"):
        StoragePolicy(configured_cap_bytes=90_000_000_001)
    governor, _ = _governor(tmp_path, 12_000_000_000)
    assert governor.dashboard().effective_cap_bytes == 0
    governor, _ = _governor(tmp_path, 50_000_000_000)
    assert governor.dashboard().effective_cap_bytes == 22_000_000_000


def test_dashboard_explains_a_reduced_cap_and_reports_retention_feasibility(tmp_path: Path) -> None:
    constrained, _ = _governor(tmp_path, 104_200_000_000)
    dashboard = constrained.dashboard()

    assert not dashboard.fits_retention_targets
    assert (
        dashboard.cap_reason
        == "filesystem availability and safety reserves lower the effective cap"
    )

    generous = FilesystemStorageGovernor(
        tmp_path,
        _catalogue(tmp_path),
        _Archive(),  # type: ignore[arg-type]
        policy=StoragePolicy(planned_session_hours=1, fallback_original_bytes_per_hour=1),
        disk_usage=_disk_usage(200_000_000_000),
    ).dashboard()
    assert generous.fits_retention_targets
    assert generous.cap_reason is None


def test_policy_and_application_facade_validate_and_delegate(tmp_path: Path) -> None:
    for kwargs in (
        {"operating_system_reserve_bytes": -1},
        {"planned_session_hours": 0},
        {"fallback_original_bytes_per_hour": 0},
    ):
        with pytest.raises(ValueError):
            StoragePolicy(**kwargs)

    governor, _ = _governor(tmp_path)
    service = StorageGovernorService(governor)
    assert service.dashboard().configured_cap_bytes == 90_000_000_000
    assert service.ensure_working_reserve(0, recording_active=False).remaining_bytes_needed == 0
    with pytest.raises(ValueError, match="cannot be negative"):
        service.ensure_working_reserve(-1, recording_active=False)
    with pytest.raises(ValueError, match="must be positive"):
        service.free_bytes(0)


def test_accounting_is_byte_accurate_and_keeps_current_partial_and_quarantine(
    tmp_path: Path,
) -> None:
    governor, _ = _governor(tmp_path)
    catalogue = governor._catalogue
    original = _media(catalogue, tmp_path, "current", "original", state="recording", bytes_=11)
    partial = tmp_path / "archives" / ".active.partial"
    partial.parent.mkdir(exist_ok=True)
    partial.write_bytes(b"partial")
    quarantined = _media(catalogue, tmp_path, "bad", "quarantine", bytes_=13)
    dashboard = governor.dashboard()

    assert dashboard.usage.originals_bytes == 11
    assert dashboard.usage.temporary_bytes == len(b"partial")
    assert dashboard.usage.quarantine_bytes == 13
    decision = governor.free_bytes(1_000_000, recording_active=True)
    assert decision.safe_stop_required
    assert original.exists() and partial.exists() and quarantined.exists()


def test_retention_order_deletes_share_then_archive_but_never_protected_or_unverified(
    tmp_path: Path,
) -> None:
    governor, _ = _governor(tmp_path)
    catalogue = governor._catalogue
    share = _media(catalogue, tmp_path, "share", "share_copy", bytes_=7)
    archive = _media(catalogue, tmp_path, "archive", "archive", bytes_=11)
    protected = _media(catalogue, tmp_path, "protected", "archive", protected=True, bytes_=17)
    unverified = _media(
        catalogue, tmp_path, "unverified", "archive", state="interrupted_unverified"
    )

    decision = governor.free_bytes(12, recording_active=True)

    assert [action.action for action in decision.actions[:2]] == [
        "deleted_share_copy",
        "deleted_archive",
    ]
    assert not share.exists() and not archive.exists()
    assert protected.exists() and unverified.exists()
    assert (tmp_path / ".storage-audit.jsonl").is_file()


def test_working_reserve_reclaims_derived_media_and_counts_external_metadata(
    tmp_path: Path,
) -> None:
    metadata = tmp_path.parent / "catalogue.sqlite"
    metadata.write_bytes(b"metadata")
    archive = _Archive()
    catalogue = _catalogue(tmp_path)
    governor = FilesystemStorageGovernor(
        tmp_path,
        catalogue,
        archive,  # type: ignore[arg-type]
        disk_usage=_disk_usage(28_000_000_000),
        metadata_paths=(metadata,),
    )
    share = _media(catalogue, tmp_path, "share", "share_copy", bytes_=7)

    decision = governor.ensure_working_reserve(5, recording_active=True)

    assert decision.remaining_bytes_needed == 0
    assert not share.exists()
    assert decision.dashboard.usage.metadata_bytes >= len(b"metadata")


def test_terminal_temporary_is_removed_only_after_recovery_analysis(tmp_path: Path) -> None:
    governor, archive = _governor(tmp_path)
    catalogue = governor._catalogue
    _media(catalogue, tmp_path, "source", "original", state="verified")
    partial = tmp_path / ".archive-work" / "job.partial"
    partial.parent.mkdir()
    partial.write_bytes(b"work")
    now = datetime.now(UTC).isoformat()
    with catalogue._catalogue.transaction():
        catalogue._catalogue.connection.execute(
            """INSERT INTO archive_jobs(
                id, segment_id, state, created_at, updated_at, work_path
            ) VALUES ('job', 'source', 'failed', ?, ?, ?)""",
            (now, now, str(partial)),
        )

    decision = governor.free_bytes(4, recording_active=True)

    assert archive.recovered == 1
    assert not partial.exists()
    assert decision.actions[0].action == "removed_stale_temporary"


def test_pressure_queues_originals_only_while_idle(tmp_path: Path) -> None:
    governor, archive = _governor(tmp_path)
    _media(governor._catalogue, tmp_path, "original-1", "original", state="verified", bytes_=20)

    idle = governor.free_bytes(10, recording_active=False)
    active = governor.free_bytes(10, recording_active=True)

    assert [action.action for action in idle.actions] == ["queued_original_archive"]
    assert archive.requests
    assert active.safe_stop_required


def test_governor_rejects_relative_roots_and_handles_a_missing_root(tmp_path: Path) -> None:
    catalogue = _catalogue(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        FilesystemStorageGovernor(Path("relative"), catalogue, _Archive())  # type: ignore[arg-type]

    missing_root = tmp_path / "not-created"
    governor, _ = _governor(missing_root)
    assert governor.dashboard().usage == StorageUsage()


def test_retention_skips_a_candidate_that_cannot_be_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    governor, _ = _governor(tmp_path)
    share = _media(governor._catalogue, tmp_path, "share", "share_copy", bytes_=7)

    def no_delete(*_args: object) -> int:
        return 0

    monkeypatch.setattr(governor._catalogue, "delete_retention_candidate", no_delete)
    decision = governor.free_bytes(7, recording_active=True)

    assert share.exists()
    assert decision.safe_stop_required
    assert [action.action for action in decision.actions] == ["safe_stop_required"]


def test_usage_ignores_links_and_external_non_files_and_safe_unlink_refuses_them(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside-media.mkv"
    outside.write_bytes(b"outside")
    linked = tmp_path / "originals" / "linked.mkv"
    linked.parent.mkdir()
    linked.symlink_to(outside)
    external_directory = tmp_path.parent / "metadata-directory"
    external_directory.mkdir()
    missing_metadata = tmp_path.parent / "missing-metadata.sqlite"
    metadata_inside_root = tmp_path / "metadata.sqlite"
    metadata_inside_root.write_bytes(b"already counted")
    governor = FilesystemStorageGovernor(
        tmp_path,
        _catalogue(tmp_path),
        _Archive(),  # type: ignore[arg-type]
        disk_usage=_disk_usage(100_000_000_000),
        metadata_paths=(linked, external_directory, missing_metadata, metadata_inside_root),
    )

    assert governor.dashboard().usage.metadata_bytes == len(b"outside") + len(b"already counted")
    assert governor._unlink_safe(linked) == 0
    assert governor._unlink_safe(missing_metadata) == 0
    assert governor._unlink_safe(outside) == 0


def test_catalogue_refresh_and_governor_decision_share_the_serialized_boundary(
    tmp_path: Path,
) -> None:
    governor, _ = _governor(tmp_path)
    _media(governor._catalogue, tmp_path, "share", "share_copy")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(governor.dashboard)
        second = executor.submit(lambda: governor._catalogue.page(LibraryFilter(), 0, 10))
        assert first.result().usage.share_copies_bytes == 10
        assert len(second.result()) == 1


class _Controller:
    def __init__(self) -> None:
        self.is_running = True
        self.progress = None
        self.events: list[tuple[str, dict[str, object]]] = []
        self.stopped = 0

    def start(self):
        from usb_cctv_recorder.domain.value_objects import SessionId
        from usb_cctv_recorder.worker.recording import StartedRecording

        return StartedRecording(SessionId.new(), Path("/tmp"), ("ffmpeg",))

    def append_event(self, event: str, payload: dict[str, object]) -> None:
        self.events.append((event, payload))

    def stop(self, *_args: object, **_kwargs: object):
        self.stopped += 1
        self.is_running = False
        return SimpleNamespace(returncode=0, forced_kill=False)

    def active_output_bytes(self) -> None:
        return None

    def poll(self) -> None:
        return None


class _CriticalGovernor:
    def dashboard(self) -> StorageDashboard:
        raise AssertionError("worker does not need dashboard")

    def ensure_working_reserve(self, _bytes: int, *, recording_active: bool) -> StorageDecision:
        return StorageDecision(
            StorageDashboard(StorageUsage(), *(0,) * 16),
            (StorageAction("safe_stop_required", None, 0, "test"),),
            recording_active,
            1 if recording_active else 0,
        )


def test_critical_storage_safe_stops_before_a_segment_boundary() -> None:
    controller = _Controller()
    supervisor = WorkerSupervisor(
        lambda: controller,  # type: ignore[arg-type]
        storage_governor=_CriticalGovernor(),  # type: ignore[arg-type]
        estimated_segment_bytes=1,
    )
    assert supervisor.handle(Request(Command.START, "start")).accepted

    supervisor.poll()

    assert supervisor.state.value == "completed"
    assert controller.stopped == 1
    assert ("finalization_requested", {"reason": "critical_storage"}) in controller.events
