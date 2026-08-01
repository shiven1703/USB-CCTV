"""Application service for Phase 3 setup validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .configuration import RecorderConfiguration
from .dto import (
    AudioSource,
    CaptureMode,
    DeviceDiscovery,
    PreflightErrorCode,
    PreflightResult,
    StorageEstimate,
    VideoDevice,
)


class DeviceDiscoveryPort(Protocol):
    def discover(self) -> DeviceDiscovery: ...


class StorageEstimatePort(Protocol):
    def estimate(self, configuration: RecorderConfiguration) -> StorageEstimate: ...


@dataclass(frozen=True, slots=True)
class SetupSelection:
    camera_stable_id: str | None
    microphone_stable_id: str | None
    capture_mode: CaptureMode | None
    configuration: RecorderConfiguration


class PreflightService:
    """Validates selections; Qt owns the actual short-lived multimedia test."""

    def __init__(
        self, discovery_port: DeviceDiscoveryPort, storage_port: StorageEstimatePort
    ) -> None:
        self._discovery_port = discovery_port
        self._storage_port = storage_port

    def discover(self) -> DeviceDiscovery:
        return self._discovery_port.discover()

    def validate(
        self,
        discovery: DeviceDiscovery,
        selection: SetupSelection,
        *,
        preview_succeeded: bool,
        preview_failed: bool = False,
    ) -> PreflightResult:
        errors: list[PreflightErrorCode] = []
        camera = self._find_camera(discovery.video_devices, selection.camera_stable_id)
        microphone = self._find_microphone(discovery.audio_sources, selection.microphone_stable_id)
        if camera is None:
            errors.append(PreflightErrorCode.CAMERA_MISSING)
        if microphone is None:
            errors.append(PreflightErrorCode.MICROPHONE_MISSING)
        if camera is not None and selection.capture_mode not in camera.capture_modes:
            errors.append(PreflightErrorCode.UNSUPPORTED_MODE)

        storage_estimate = self._storage_port.estimate(selection.configuration)
        if not storage_estimate.usable:
            errors.append(PreflightErrorCode.OUTPUT_DIRECTORY)
        elif storage_estimate.safe_recording_bytes <= 0:
            errors.append(PreflightErrorCode.INSUFFICIENT_STORAGE)
        if preview_failed:
            errors.append(PreflightErrorCode.PREVIEW_FAILED)
        elif not preview_succeeded:
            errors.append(PreflightErrorCode.PREVIEW_REQUIRED)
        return PreflightResult(tuple(errors), storage_estimate)

    @staticmethod
    def _find_camera(devices: tuple[VideoDevice, ...], stable_id: str | None) -> VideoDevice | None:
        return next((device for device in devices if device.stable_id == stable_id), None)

    @staticmethod
    def _find_microphone(
        sources: tuple[AudioSource, ...], stable_id: str | None
    ) -> AudioSource | None:
        return next((source for source in sources if source.stable_id == stable_id), None)
