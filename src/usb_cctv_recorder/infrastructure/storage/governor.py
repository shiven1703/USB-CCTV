"""Evidence-safe Phase 10 storage accounting and pressure governor."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from threading import RLock

from usb_cctv_recorder.application.dto import ArchiveProfile, ArchiveProfileKind, ArchiveRequest
from usb_cctv_recorder.application.ports import WallAndMonotonicClock
from usb_cctv_recorder.application.storage import (
    StorageAction,
    StorageDashboard,
    StorageDecision,
    StoragePolicy,
    StorageUsage,
)
from usb_cctv_recorder.infrastructure.persistence.event_journal import (
    JournalEvent,
    JsonlEventJournal,
)
from usb_cctv_recorder.infrastructure.persistence.library_catalogue import SQLiteLibraryCatalogue
from usb_cctv_recorder.infrastructure.storage.archive_transaction import ArchiveTransactionManager


class FilesystemStorageGovernor:
    """Serializes destructive retention operations and records every automatic action."""

    def __init__(
        self,
        media_root: Path,
        catalogue: SQLiteLibraryCatalogue,
        archive: ArchiveTransactionManager,
        policy: StoragePolicy | None = None,
        *,
        disk_usage: Callable[[Path], shutil._ntuple_diskusage] = shutil.disk_usage,
        metadata_paths: tuple[Path, ...] = (),
    ) -> None:
        if not media_root.is_absolute():
            raise ValueError("media root must be absolute")
        self._root = media_root.resolve()
        self._catalogue = catalogue
        self._archive = archive
        self._policy = policy or StoragePolicy()
        self._disk_usage = disk_usage
        self._metadata_paths = tuple(path.resolve(strict=False) for path in metadata_paths)
        self._lock = RLock()
        self._journal = JsonlEventJournal(self._root / ".storage-audit.jsonl")
        self._clock = WallAndMonotonicClock()

    def dashboard(self) -> StorageDashboard:
        with self._lock:
            return self._dashboard()

    def ensure_working_reserve(
        self, required_bytes: int, *, recording_active: bool
    ) -> StorageDecision:
        if required_bytes < 0:
            raise ValueError("required storage bytes cannot be negative")
        with self._lock:
            dashboard = self._dashboard()
            needed = max(
                dashboard.usage.total_bytes + required_bytes - dashboard.effective_cap_bytes,
                self._policy.operating_system_reserve_bytes
                + self._policy.emergency_finalization_reserve_bytes
                + required_bytes
                - dashboard.filesystem_free_bytes,
                0,
            )
            return self._reclaim(needed, dashboard, recording_active=recording_active)

    def free_bytes(self, requested_bytes: int, *, recording_active: bool) -> StorageDecision:
        if requested_bytes <= 0:
            raise ValueError("requested free space must be positive")
        with self._lock:
            return self._reclaim(
                requested_bytes, self._dashboard(), recording_active=recording_active
            )

    def _reclaim(
        self, needed: int, dashboard: StorageDashboard, *, recording_active: bool
    ) -> StorageDecision:
        if needed == 0:
            return StorageDecision(dashboard, (), False, 0)
        actions: list[StorageAction] = []
        # Phase 9 recovery makes unfinished work visible before any stale work is removed.
        self._archive.recover_partials()
        for path in self._catalogue.safe_temporary_paths(self._root):
            freed = self._unlink_safe(path)
            if freed:
                action = StorageAction("removed_stale_temporary", None, freed, str(path))
                actions.append(action)
                self._audit(action)
                needed = max(0, needed - freed)
                if needed == 0:
                    return StorageDecision(self._dashboard(), tuple(actions), False, 0)
        for media_class in ("share_copy", "archive"):
            for item in self._catalogue.retention_candidates(media_class, self._root):
                if needed == 0:
                    break
                path = Path(item.file_path or "")
                freed = self._catalogue.delete_retention_candidate(
                    item.item_id, self._root, self._unlink_safe
                )
                if not freed:
                    continue
                action = StorageAction(f"deleted_{media_class}", item.item_id, freed, str(path))
                actions.append(action)
                self._audit(action)
                needed = max(0, needed - freed)
            if needed == 0:
                return StorageDecision(self._dashboard(), tuple(actions), False, 0)
        if not recording_active:
            originals = self._catalogue.eligible_original_ids(requested_bytes=needed)
            if originals:
                queued = self._archive.enqueue(
                    ArchiveRequest(
                        originals,
                        ArchiveProfile(ArchiveProfileKind.COMPRESSED),
                        str(self._root),
                        delete_sources_after_commit=False,
                    )
                )
                for job in queued:
                    action = StorageAction(
                        "queued_original_archive", job.source_item_id, 0, job.job_id
                    )
                    actions.append(action)
                    self._audit(action)
        # Queueing cannot satisfy present pressure; originals are intentionally never auto-deleted.
        safe_stop = recording_active and needed > 0
        if safe_stop:
            action = StorageAction("safe_stop_required", None, 0, "no safe deletion candidate")
            actions.append(action)
            self._audit(action)
        return StorageDecision(self._dashboard(), tuple(actions), safe_stop, needed)

    def _dashboard(self) -> StorageDashboard:
        usage = self._usage()
        available = self._disk_usage(self._existing_parent()).free
        effective = max(
            0,
            min(
                self._policy.configured_cap_bytes,
                90_000_000_000,
                usage.total_bytes
                + available
                - self._policy.operating_system_reserve_bytes
                - self._policy.emergency_finalization_reserve_bytes,
            ),
        )
        original_rate, archive_rate = self._catalogue.measured_storage_rates(
            self._policy.fallback_original_bytes_per_hour
        )
        next_session = round(original_rate * self._policy.planned_session_hours)
        original_pool = effective * 52 // 100
        archive_pool = effective * 33 // 100
        metadata_pool = effective * 5 // 100
        headroom = effective - original_pool - archive_pool - metadata_pool
        original_nights = original_pool // max(1, next_session)
        archive_session = round(archive_rate * self._policy.planned_session_hours)
        history_nights = original_nights + archive_pool // max(1, archive_session)
        return StorageDashboard(
            usage,
            available,
            effective,
            self._policy.configured_cap_bytes,
            self._policy.operating_system_reserve_bytes,
            self._policy.emergency_finalization_reserve_bytes,
            original_pool,
            archive_pool,
            metadata_pool,
            headroom,
            original_rate,
            archive_rate,
            next_session,
            next_session * 3,
            next_session * 7,
            original_nights,
            history_nights,
        )

    def _usage(self) -> StorageUsage:
        categories = {name: 0 for name in StorageUsage.__dataclass_fields__}
        if not self._root.is_dir():
            return StorageUsage()
        for directory, _names, files in os.walk(self._root, followlinks=False):
            current = Path(directory)
            for name in files:
                path = current / name
                try:
                    status = path.lstat()
                except OSError:
                    continue
                if not path.is_file() or path.is_symlink():
                    continue
                categories[self._category(path)] += status.st_size
        for path in self._metadata_paths:
            try:
                path.relative_to(self._root)
                continue
            except ValueError:
                pass
            try:
                status = path.lstat()
            except OSError:
                continue
            if path.is_file() and not path.is_symlink():
                categories["metadata_bytes"] += status.st_size
        return StorageUsage(**categories)

    def _category(self, path: Path) -> str:
        relative = path.relative_to(self._root)
        first = relative.parts[0] if relative.parts else ""
        if first == "originals":
            return "originals_bytes"
        if first == "quarantine":
            return "quarantine_bytes"
        if first in {"share", "share-copies", "share_copies"}:
            return "share_copies_bytes"
        if first == ".archive-work" or path.name.endswith(".partial"):
            return "temporary_bytes"
        if first == "archives":
            return "archives_bytes"
        return "metadata_bytes"

    def _existing_parent(self) -> Path:
        candidate = self._root
        while not candidate.exists() and candidate.parent != candidate:
            candidate = candidate.parent
        return candidate

    def _unlink_safe(self, path: Path) -> int:
        try:
            resolved_parent = path.parent.resolve(strict=True)
            resolved_parent.relative_to(self._root)
            status = path.lstat()
            if path.is_symlink() or not path.is_file():
                return 0
            size = status.st_size
            path.unlink()
            return size
        except (OSError, ValueError):
            return 0

    def _audit(self, action: StorageAction) -> None:
        self._journal.append(
            JournalEvent(
                "storage_governor_action",
                self._clock.now(),
                {
                    "action": action.action,
                    "item_id": action.item_id,
                    "bytes_affected": action.bytes_affected,
                    "detail": action.detail,
                },
            )
        )
