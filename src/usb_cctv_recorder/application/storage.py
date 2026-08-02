"""Application-facing storage policy, estimates, and retention decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .configuration import (
    DEFAULT_EMERGENCY_FINALIZATION_RESERVE_BYTES,
    DEFAULT_OPERATING_SYSTEM_RESERVE_BYTES,
    MAX_MANAGED_STORAGE_BYTES,
)


@dataclass(frozen=True, slots=True)
class StoragePolicy:
    """The conservative Phase 10 policy; all sizes are decimal bytes."""

    configured_cap_bytes: int = MAX_MANAGED_STORAGE_BYTES
    operating_system_reserve_bytes: int = DEFAULT_OPERATING_SYSTEM_RESERVE_BYTES
    emergency_finalization_reserve_bytes: int = DEFAULT_EMERGENCY_FINALIZATION_RESERVE_BYTES
    planned_session_hours: float = 8.0
    fallback_original_bytes_per_hour: int = 1_650_000_000

    def __post_init__(self) -> None:
        if not 0 <= self.configured_cap_bytes <= MAX_MANAGED_STORAGE_BYTES:
            raise ValueError("configured storage cap must not exceed 90,000,000,000 bytes")
        if min(self.operating_system_reserve_bytes, self.emergency_finalization_reserve_bytes) < 0:
            raise ValueError("storage reserves cannot be negative")
        if self.planned_session_hours <= 0 or self.fallback_original_bytes_per_hour <= 0:
            raise ValueError("planned session and fallback rate must be positive")


@dataclass(frozen=True, slots=True)
class StorageUsage:
    originals_bytes: int = 0
    archives_bytes: int = 0
    metadata_bytes: int = 0
    quarantine_bytes: int = 0
    share_copies_bytes: int = 0
    temporary_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return sum(
            (
                self.originals_bytes,
                self.archives_bytes,
                self.metadata_bytes,
                self.quarantine_bytes,
                self.share_copies_bytes,
                self.temporary_bytes,
            )
        )


@dataclass(frozen=True, slots=True)
class StorageDashboard:
    """Actual usage and deliberately separate advisory estimates."""

    usage: StorageUsage
    filesystem_free_bytes: int
    effective_cap_bytes: int
    configured_cap_bytes: int
    operating_system_reserve_bytes: int
    emergency_finalization_reserve_bytes: int
    original_pool_bytes: int
    archive_pool_bytes: int
    metadata_pool_bytes: int
    transaction_headroom_bytes: int
    measured_original_bytes_per_hour: int
    measured_archive_bytes_per_hour: int
    estimated_next_session_bytes: int
    estimated_three_night_original_bytes: int
    estimated_seven_night_history_bytes: int
    estimated_original_nights: int
    estimated_history_nights: int

    @property
    def fits_retention_targets(self) -> bool:
        return self.estimated_original_nights >= 3 and self.estimated_history_nights >= 7

    @property
    def cap_reason(self) -> str | None:
        if self.effective_cap_bytes < self.configured_cap_bytes:
            return "filesystem availability and safety reserves lower the effective cap"
        return None


@dataclass(frozen=True, slots=True)
class StorageAction:
    action: str
    item_id: str | None
    bytes_affected: int
    detail: str


@dataclass(frozen=True, slots=True)
class StorageDecision:
    dashboard: StorageDashboard
    actions: tuple[StorageAction, ...]
    safe_stop_required: bool
    remaining_bytes_needed: int


class StorageGovernorPort(Protocol):
    def dashboard(self) -> StorageDashboard: ...

    def ensure_working_reserve(
        self, required_bytes: int, *, recording_active: bool
    ) -> StorageDecision: ...

    def free_bytes(self, requested_bytes: int, *, recording_active: bool) -> StorageDecision: ...


class StorageGovernorService:
    """Keeps Qt and the worker away from filesystem and catalogue ownership."""

    def __init__(self, governor: StorageGovernorPort) -> None:
        self._governor = governor

    def dashboard(self) -> StorageDashboard:
        return self._governor.dashboard()

    def ensure_working_reserve(
        self, required_bytes: int, *, recording_active: bool
    ) -> StorageDecision:
        return self._governor.ensure_working_reserve(
            required_bytes, recording_active=recording_active
        )

    def free_bytes(
        self, requested_bytes: int, *, recording_active: bool = False
    ) -> StorageDecision:
        return self._governor.free_bytes(requested_bytes, recording_active=recording_active)
