"""Validated worker-readable configuration without Qt dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_MANAGED_STORAGE_BYTES = 90_000_000_000
DEFAULT_OPERATING_SYSTEM_RESERVE_BYTES = 20_000_000_000
DEFAULT_EMERGENCY_FINALIZATION_RESERVE_BYTES = 8_000_000_000


@dataclass(frozen=True, slots=True)
class RecorderConfiguration:
    """Configuration values that affect recording safety and storage policy."""

    media_root: Path
    segment_duration_minutes: int = 60
    configured_storage_cap_bytes: int = MAX_MANAGED_STORAGE_BYTES
    operating_system_reserve_bytes: int = DEFAULT_OPERATING_SYSTEM_RESERVE_BYTES
    emergency_finalization_reserve_bytes: int = DEFAULT_EMERGENCY_FINALIZATION_RESERVE_BYTES

    def __post_init__(self) -> None:
        if not self.media_root.is_absolute():
            raise ValueError("media root must be an absolute path")
        if not 1 <= self.segment_duration_minutes <= 360:
            raise ValueError("segment duration must be between 1 and 360 minutes")
        if not 0 <= self.configured_storage_cap_bytes <= MAX_MANAGED_STORAGE_BYTES:
            raise ValueError("configured storage cap must be between 0 and 90,000,000,000 bytes")
        if self.operating_system_reserve_bytes < 0:
            raise ValueError("operating-system reserve cannot be negative")
        if self.emergency_finalization_reserve_bytes < 0:
            raise ValueError("emergency finalization reserve cannot be negative")


@dataclass(frozen=True, slots=True)
class WorkerRecordingConfiguration:
    """Validated capture settings persisted for the independent service worker."""

    media_root: Path
    camera_identity: str
    microphone_source: str
    width: int
    height: int
    input_frame_rate: float
    output_frame_rate: float
    segment_duration_minutes: int

    def __post_init__(self) -> None:
        if not self.media_root.is_absolute():
            raise ValueError("media root must be absolute")
        if not self.camera_identity.startswith("/dev/v4l/by-id/"):
            raise ValueError("camera identity must be a persistent /dev/v4l/by-id path")
        if not self.microphone_source or self.microphone_source in {"default", "@DEFAULT_SOURCE@"}:
            raise ValueError("microphone source must be explicit")
        if self.width <= 0 or self.height <= 0 or self.input_frame_rate <= 0:
            raise ValueError("capture dimensions and input frame rate must be positive")
        if self.output_frame_rate not in {12, 15}:
            raise ValueError("output frame rate must be 12 or 15")
        if not 1 <= self.segment_duration_minutes <= 360:
            raise ValueError("segment duration must be between 1 and 360 minutes")
