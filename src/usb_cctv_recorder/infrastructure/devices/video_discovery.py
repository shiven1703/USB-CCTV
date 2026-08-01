"""V4L2 capture discovery using stable /dev/v4l aliases."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from usb_cctv_recorder.application.dto import (
    CaptureMode,
    DiscoveryError,
    DiscoveryErrorCode,
    VideoDevice,
)
from usb_cctv_recorder.infrastructure.commands.runner import CommandResult, StructuredCommandRunner

_DEVICE_HEADER = re.compile(r"^(?P<name>.+):$")
_FORMAT = re.compile(r"^\[\d+\]: '(?P<format>[^']+)' \((?P<name>.+)\)")
_SIZE = re.compile(r"^Size: Discrete (?P<width>\d+)x(?P<height>\d+)")
_FPS = re.compile(r"\((?P<fps>[0-9.]+) fps\)")


def parse_v4l2_devices(output: str) -> tuple[tuple[str, str], ...]:
    """Return (friendly name, transient node) pairs from ``--list-devices``."""
    devices: list[tuple[str, str]] = []
    current_name: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        header = _DEVICE_HEADER.match(line)
        if raw_line and not raw_line[0].isspace() and header:
            current_name = header.group("name")
        elif current_name is not None and line.startswith("/dev/video"):
            devices.append((current_name, line))
    return tuple(devices)


def parse_v4l2_capture_modes(output: str) -> tuple[CaptureMode, ...]:
    """Parse only video-capture format entries with a usable frame rate."""
    if "Type: Video Capture" not in output:
        return ()
    modes: list[CaptureMode] = []
    pixel_format = ""
    format_name = ""
    dimensions: tuple[int, int] | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        format_match = _FORMAT.match(line)
        if format_match:
            pixel_format = format_match.group("format")
            format_name = format_match.group("name")
            dimensions = None
            continue
        size_match = _SIZE.match(line)
        if size_match:
            dimensions = (int(size_match.group("width")), int(size_match.group("height")))
            continue
        fps_match = _FPS.search(line)
        if fps_match and dimensions is not None and pixel_format:
            frames_per_second = float(fps_match.group("fps"))
            # Phase 3 does not offer 1 FPS surveillance modes. A later profile probe can
            # introduce a product-specific lower rate deliberately if it is useful.
            if frames_per_second > 1:
                modes.append(
                    CaptureMode(
                        pixel_format,
                        format_name,
                        dimensions[0],
                        dimensions[1],
                        frames_per_second,
                    )
                )
    return tuple(modes)


def stable_aliases(
    device_path: str, alias_directory: Path = Path("/dev/v4l/by-id")
) -> tuple[str, ...]:
    """Find by-id aliases targeting the current transient V4L2 node."""
    try:
        resolved_device = Path(device_path).resolve(strict=True)
        aliases = [
            str(path)
            for path in alias_directory.iterdir()
            if path.resolve(strict=True) == resolved_device
        ]
    except OSError:
        return ()
    return tuple(sorted(aliases))


class V4l2VideoDiscovery:
    """Adapter for documented ``v4l2-ctl`` listing commands."""

    def __init__(
        self,
        runner: StructuredCommandRunner,
        alias_lookup: Callable[[str], tuple[str, ...]] = stable_aliases,
    ) -> None:
        self._runner = runner
        self._alias_lookup = alias_lookup

    def list_video_devices(self) -> tuple[VideoDevice, ...]:
        devices, _ = self.discover()
        return devices

    def discover(self) -> tuple[tuple[VideoDevice, ...], DiscoveryError | None]:
        listed = self._runner.run(("v4l2-ctl", "--list-devices"))
        if not listed.succeeded:
            return (), _discovery_error(listed, "camera")
        devices: list[VideoDevice] = []
        for friendly_name, current_path in parse_v4l2_devices(listed.stdout):
            formats = self._runner.run(("v4l2-ctl", "--device", current_path, "--list-formats-ext"))
            if not formats.succeeded:
                continue
            modes = parse_v4l2_capture_modes(formats.stdout)
            aliases = self._alias_lookup(current_path)
            if not modes or not aliases:
                continue
            # A webcam can expose a metadata sibling. Only capture modes survive above.
            devices.append(VideoDevice(aliases[0], friendly_name, current_path, modes))
        return tuple(devices), None


def _discovery_error(result: CommandResult, device_kind: str) -> DiscoveryError:
    combined_output = f"{result.stdout}\n{result.stderr}\n{result.execution_error or ''}".lower()
    if "permission denied" in combined_output:
        return DiscoveryError(
            DiscoveryErrorCode.PERMISSION_DENIED, f"Permission denied while listing {device_kind}s."
        )
    if result.execution_error is not None:
        return DiscoveryError(
            DiscoveryErrorCode.MISSING, f"Cannot run the {device_kind} discovery tool."
        )
    return DiscoveryError(DiscoveryErrorCode.COMMAND_FAILED, f"Unable to list {device_kind}s.")
