"""Read-only storage estimate for the Phase 3 setup page."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from usb_cctv_recorder.application.configuration import RecorderConfiguration
from usb_cctv_recorder.application.dto import StorageEstimate


class FilesystemStorageEstimate:
    """Uses the selected directory's filesystem without creating or modifying it."""

    def estimate(self, configuration: RecorderConfiguration) -> StorageEstimate:
        inspected_path = _existing_parent(configuration.media_root)
        if inspected_path is None or not configuration.media_root.is_dir():
            return StorageEstimate(0, 0, "Choose an existing recording directory.", usable=False)
        if not os.access(configuration.media_root, os.W_OK | os.X_OK):
            return StorageEstimate(0, 0, "The recording directory is not writable.", usable=False)
        available_bytes = shutil.disk_usage(inspected_path).free
        safe_recording_bytes = max(
            0,
            min(
                configuration.configured_storage_cap_bytes,
                available_bytes
                - configuration.operating_system_reserve_bytes
                - configuration.emergency_finalization_reserve_bytes,
            ),
        )
        return StorageEstimate(
            available_bytes,
            safe_recording_bytes,
            f"Estimated safe recording space: {_format_bytes(safe_recording_bytes)}.",
        )


def _existing_parent(path: Path) -> Path | None:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate if candidate.exists() else None


def _format_bytes(value: int) -> str:
    return f"{value / 1_000_000_000:.1f} GB"
