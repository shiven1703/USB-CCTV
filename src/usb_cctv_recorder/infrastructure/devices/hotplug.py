"""Udev-backed V4L2 hotplug notifications and persistent identity resolution."""

from __future__ import annotations

import queue
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True, slots=True)
class VideoDeviceEvent:
    """One parsed ``udevadm monitor --property`` video4linux event."""

    action: str
    device_path: str | None
    properties: dict[str, str]


def parse_udevadm_events(output: str) -> tuple[VideoDeviceEvent, ...]:
    """Parse property blocks emitted by the locally documented udev monitor."""
    events: list[VideoDeviceEvent] = []
    properties: dict[str, str] = {}
    for raw_line in (*output.splitlines(), ""):
        line = raw_line.strip()
        if not line:
            if properties.get("SUBSYSTEM") == "video4linux" and properties.get("ACTION"):
                events.append(
                    VideoDeviceEvent(
                        properties["ACTION"], properties.get("DEVNAME"), dict(properties)
                    )
                )
            properties.clear()
            continue
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return tuple(events)


def resolve_video_identity(identity: str) -> Path | None:
    """Resolve exactly the selected persistent alias, never a transient substitute."""
    path = Path(identity)
    if not identity.startswith("/dev/v4l/by-id/"):
        raise ValueError("camera identity must be a persistent /dev/v4l/by-id path")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    if not resolved.name.startswith("video"):
        return None
    return resolved


class UdevVideoHotplugMonitor:
    """Reads only video4linux udev events; a worker polls the in-memory queue."""

    _ARGUMENTS = (
        "udevadm",
        "monitor",
        "--udev",
        "--property",
        "--subsystem-match=video4linux",
    )

    def __init__(
        self,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self._popen = popen
        self._process: subprocess.Popen[str] | None = None
        self._events: queue.SimpleQueue[VideoDeviceEvent] = queue.SimpleQueue()
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = self._popen(
            self._ARGUMENTS,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            shell=False,
        )
        if self._process.stdout is None:
            raise RuntimeError("udev monitor did not provide stdout")
        self._reader = threading.Thread(
            target=self._read_events, args=(self._process.stdout,), daemon=True
        )
        self._reader.start()

    def poll(self) -> tuple[VideoDeviceEvent, ...]:
        events: list[VideoDeviceEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return tuple(events)

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
        if self._reader is not None:
            self._reader.join(timeout=1)
        self._reader = None
        self._process = None

    def _read_events(self, stream: TextIO) -> None:
        properties: dict[str, str] = {}
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                for event in parse_udevadm_events(
                    "\n".join(f"{key}={value}" for key, value in properties.items())
                ):
                    self._events.put(event)
                properties.clear()
                continue
            key, separator, value = line.partition("=")
            if separator:
                properties[key] = value
