"""Runtime-only logind inhibition through the supported systemd-inhibit wrapper."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable
from typing import Protocol


class InhibitionError(RuntimeError):
    """logind could not provide the required recording protection."""


class _Process(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


PopenFactory = Callable[..., _Process]


class SystemdInhibitAdapter:
    """Holds explicit logind locks in worker-owned process groups.

    ``systemd-inhibit`` is the locally verified systemd 255 wrapper for logind's
    inhibitor API. Its child remains alive until this adapter releases it, which
    closes the associated logind handle without changing desktop configuration.
    """

    def __init__(
        self,
        popen: PopenFactory = subprocess.Popen,
        *,
        executable: str = "systemd-inhibit",
        sleeper: str = "/usr/bin/sleep",
    ) -> None:
        self._popen = popen
        self._executable = executable
        self._sleeper = sleeper
        self._block_process: _Process | None = None
        self._shutdown_process: _Process | None = None

    def acquire(self, *, block_lid_close: bool) -> None:
        if self.protection_active():
            return
        self.release()
        what = "sleep:idle"
        if block_lid_close:
            what += ":handle-lid-switch"
        try:
            self._block_process = self._start(what, "block")
            self._shutdown_process = self._start("shutdown", "delay")
        except (OSError, InhibitionError) as error:
            self.release()
            raise InhibitionError(f"unable to acquire logind inhibition: {error}") from error

    def release(self) -> None:
        for process in (self._shutdown_process, self._block_process):
            if process is not None:
                self._terminate(process)
        self._block_process = None
        self._shutdown_process = None

    def protection_active(self) -> bool:
        return (
            self._block_process is not None
            and self._shutdown_process is not None
            and self._block_process.poll() is None
            and self._shutdown_process.poll() is None
        )

    def _start(self, what: str, mode: str) -> _Process:
        process = self._popen(
            (
                self._executable,
                f"--what={what}",
                f"--mode={mode}",
                "--who=USB CCTV Recorder",
                "--why=Recording active; preserve final media segment",
                self._sleeper,
                "infinity",
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            start_new_session=True,
        )
        if process.poll() is not None:
            raise InhibitionError("systemd-inhibit exited before it acquired a handle")
        return process

    @staticmethod
    def _terminate(process: _Process) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                return
            process.wait(timeout=2)
