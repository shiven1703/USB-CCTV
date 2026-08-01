"""Structured subprocess execution for infrastructure adapters."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandResult:
    arguments: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    execution_error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and self.execution_error is None


class StructuredCommandRunner:
    """Runs a validated argv sequence; shell parsing is intentionally unavailable."""

    def __init__(self, timeout_seconds: float = 10) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, arguments: Sequence[str]) -> CommandResult:
        if not arguments or not all(
            isinstance(argument, str) and argument for argument in arguments
        ):
            raise ValueError("command arguments must be a non-empty sequence of strings")
        argv = tuple(arguments)
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                shell=False,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            return CommandResult(
                argv,
                None,
                _text(error.stdout),
                _text(error.stderr),
                f"command timed out after {self._timeout_seconds:g} seconds",
            )
        except OSError as error:
            return CommandResult(argv, None, "", "", f"{type(error).__name__}: {error}")
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)


def _text(value: bytes | str | None) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
