"""Structured adapter for the recorder's static systemd user service."""

from __future__ import annotations

from collections.abc import Sequence

from usb_cctv_recorder.infrastructure.commands.runner import CommandResult, StructuredCommandRunner

UNIT_NAME = "usb-cctv-recorder-worker.service"


class SystemdUserServiceError(RuntimeError):
    """The user manager did not accept a recorder service operation."""


class SystemdUserService:
    def __init__(self, runner: StructuredCommandRunner | None = None) -> None:
        self._runner = runner or StructuredCommandRunner()

    def start_worker(self) -> None:
        # A package upgrade can replace this static unit while the user manager is running.
        # Reload in the owning user session; never enable the worker at login.
        self._run(("systemctl", "--user", "daemon-reload"))
        self._run(("systemctl", "--user", "start", UNIT_NAME))

    def stop_worker(self) -> None:
        self._run(("systemctl", "--user", "stop", UNIT_NAME))

    def _run(self, arguments: Sequence[str]) -> CommandResult:
        result = self._runner.run(arguments)
        if not result.succeeded:
            detail = result.stderr.strip() or result.execution_error or "unknown manager failure"
            raise SystemdUserServiceError(detail)
        return result
