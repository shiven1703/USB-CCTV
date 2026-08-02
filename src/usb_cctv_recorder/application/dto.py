"""DTOs used to present discovered capture devices without leaking adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class CaptureMode:
    """A capture mode verified by V4L2 capability enumeration."""

    pixel_format: str
    pixel_format_label: str
    width: int
    height: int
    frames_per_second: float

    @property
    def label(self) -> str:
        return (
            f"{self.width} × {self.height} — {self.frames_per_second:g} FPS "
            f"({self.pixel_format_label})"
        )


@dataclass(frozen=True, slots=True)
class VideoDevice:
    """A capture-capable V4L2 device with a persistent identity."""

    stable_id: str
    friendly_name: str
    current_path: str
    capture_modes: tuple[CaptureMode, ...]

    @property
    def label(self) -> str:
        return f"{self.friendly_name} [{self.stable_id}]"


@dataclass(frozen=True, slots=True)
class AudioSource:
    """A Pulse source; ``stable_id`` is its named source, never its index."""

    stable_id: str
    friendly_name: str
    sample_specification: str

    @property
    def label(self) -> str:
        return f"{self.friendly_name} [{self.stable_id}]"


@dataclass(frozen=True, slots=True)
class FfmpegCapabilities:
    """Reported FFmpeg capabilities, not a claim that an encoder can run."""

    encoder_candidates: tuple[str, ...]
    muxers: tuple[str, ...]


class DiscoveryErrorCode(StrEnum):
    MISSING = "missing"
    PERMISSION_DENIED = "permission_denied"
    COMMAND_FAILED = "command_failed"


@dataclass(frozen=True, slots=True)
class DiscoveryError:
    code: DiscoveryErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class DeviceDiscovery:
    video_devices: tuple[VideoDevice, ...]
    audio_sources: tuple[AudioSource, ...]
    video_error: DiscoveryError | None = None
    audio_error: DiscoveryError | None = None


class PreflightErrorCode(StrEnum):
    CAMERA_MISSING = "camera_missing"
    MICROPHONE_MISSING = "microphone_missing"
    UNSUPPORTED_MODE = "unsupported_mode"
    OUTPUT_DIRECTORY = "output_directory"
    INSUFFICIENT_STORAGE = "insufficient_storage"
    PREVIEW_REQUIRED = "preview_required"
    PREVIEW_FAILED = "preview_failed"


@dataclass(frozen=True, slots=True)
class StorageEstimate:
    available_bytes: int
    safe_recording_bytes: int
    message: str
    usable: bool = True


@dataclass(frozen=True, slots=True)
class PreflightResult:
    errors: tuple[PreflightErrorCode, ...]
    storage_estimate: StorageEstimate | None

    @property
    def ready(self) -> bool:
        return not self.errors and self.storage_estimate is not None


class PowerProtectionState(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    LOST = "lost"


class PowerSource(StrEnum):
    AC = "ac"
    BATTERY = "battery"
    CRITICAL_BATTERY = "critical_battery"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PowerStatus:
    """Worker-facing power state that can be safely exposed over local IPC."""

    protection: PowerProtectionState
    source: PowerSource
    battery_percent: int | None = None


@dataclass(frozen=True, slots=True)
class LibraryFilter:
    """Optional catalogue filters; empty values deliberately mean all records."""

    date: str | None = None
    session_id: str | None = None
    media_class: str | None = None
    protected: bool | None = None
    validation_state: str | None = None
    gap_state: str | None = None


@dataclass(frozen=True, slots=True)
class LibraryItem:
    item_id: str
    kind: str
    session_id: str
    media_class: str
    file_path: str | None
    started_at: str
    duration_seconds: float | None
    protected: bool
    validation_state: str
    gap_state: str
    segment_state: str | None
    error_state: str | None


@dataclass(frozen=True, slots=True)
class LibraryDetails:
    item: LibraryItem
    facts: tuple[tuple[str, str], ...]
