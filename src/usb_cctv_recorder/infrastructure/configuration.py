"""XDG path resolution for private application data."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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
