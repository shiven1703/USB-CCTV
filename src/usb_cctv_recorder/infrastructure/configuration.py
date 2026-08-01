"""XDG path resolution for private application data."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from usb_cctv_recorder.application.configuration import WorkerRecordingConfiguration

APPLICATION_DIRECTORY_NAME = "usb-cctv-recorder"


@dataclass(frozen=True, slots=True)
class XdgPaths:
    config: Path
    state: Path
    cache: Path
    runtime: Path
    media: Path

    @classmethod
    def resolve(cls, environment: Mapping[str, str] | None = None) -> XdgPaths:
        values = os.environ if environment is None else environment
        home = Path(values.get("HOME", str(Path.home())))
        config_home = Path(values.get("XDG_CONFIG_HOME", home / ".config"))
        state_home = Path(values.get("XDG_STATE_HOME", home / ".local" / "state"))
        cache_home = Path(values.get("XDG_CACHE_HOME", home / ".cache"))
        runtime_home = values.get("XDG_RUNTIME_DIR")
        if not runtime_home:
            raise ValueError("XDG_RUNTIME_DIR is required for the worker runtime directory")
        return cls(
            config=config_home / APPLICATION_DIRECTORY_NAME,
            state=state_home / APPLICATION_DIRECTORY_NAME,
            cache=cache_home / APPLICATION_DIRECTORY_NAME,
            runtime=Path(runtime_home) / APPLICATION_DIRECTORY_NAME,
            media=home / "Videos" / "USB-CCTV-Recorder",
        )

    def create_private_directories(self) -> None:
        previous_umask = os.umask(0o077)
        try:
            for path in (self.config, self.state, self.cache, self.runtime):
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.chmod(0o700)
        finally:
            os.umask(previous_umask)


class WorkerConfigurationStore:
    """Private JSON persistence for worker-owned capture settings, never IPC input."""

    _FILENAME = "worker-recording.json"

    def __init__(self, paths: XdgPaths) -> None:
        self._paths = paths

    def save(self, configuration: WorkerRecordingConfiguration) -> None:
        self._paths.create_private_directories()
        destination = self._paths.config / self._FILENAME
        temporary = destination.with_suffix(".tmp")
        content = json.dumps(
            {
                "media_root": str(configuration.media_root),
                "camera_identity": configuration.camera_identity,
                "microphone_source": configuration.microphone_source,
                "width": configuration.width,
                "height": configuration.height,
                "input_frame_rate": configuration.input_frame_rate,
                "output_frame_rate": configuration.output_frame_rate,
                "segment_duration_minutes": configuration.segment_duration_minutes,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, destination)
        destination.chmod(0o600)

    def load(self) -> WorkerRecordingConfiguration | None:
        path = self._paths.config / self._FILENAME
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        status = path.stat()
        if status.st_uid != os.getuid() or status.st_mode & 0o077:
            raise ValueError("worker recording configuration is not private")
        try:
            fields = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("worker recording configuration is invalid JSON") from error
        expected = {
            "media_root",
            "camera_identity",
            "microphone_source",
            "width",
            "height",
            "input_frame_rate",
            "output_frame_rate",
            "segment_duration_minutes",
        }
        if not isinstance(fields, dict) or set(fields) != expected:
            raise ValueError("worker recording configuration fields are invalid")
        string_fields = ("media_root", "camera_identity", "microphone_source")
        integer_fields = ("width", "height", "segment_duration_minutes")
        float_fields = ("input_frame_rate", "output_frame_rate")
        if (
            not all(isinstance(fields[name], str) for name in string_fields)
            or not all(
                isinstance(fields[name], int) and not isinstance(fields[name], bool)
                for name in integer_fields
            )
            or not all(
                isinstance(fields[name], int | float) and not isinstance(fields[name], bool)
                for name in float_fields
            )
        ):
            raise ValueError("worker recording configuration value types are invalid")
        return WorkerRecordingConfiguration(
            media_root=Path(fields["media_root"]),
            camera_identity=fields["camera_identity"],
            microphone_source=fields["microphone_source"],
            width=fields["width"],
            height=fields["height"],
            input_frame_rate=float(fields["input_frame_rate"]),
            output_frame_rate=float(fields["output_frame_rate"]),
            segment_duration_minutes=fields["segment_duration_minutes"],
        )
