"""Bounded, process-group-aware lifecycle management for FFmpeg."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO

from .progress_parser import FfmpegProgressParser, ProgressSnapshot


class ProcessLifecycleError(RuntimeError):
    """The process could not be started or stopped through its expected lifecycle."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    arguments: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    graceful_stop_requested: bool
    forced_kill: bool
    timed_out: bool


class _BoundedTextBuffer:
    def __init__(self, maximum_bytes: int) -> None:
        self._maximum_bytes = maximum_bytes
        self._value = bytearray()
        self._lock = threading.Lock()

    def append(self, value: bytes) -> None:
        with self._lock:
            self._value.extend(value)
            overflow = len(self._value) - self._maximum_bytes
            if overflow > 0:
                del self._value[:overflow]

    def text(self) -> str:
        with self._lock:
            return bytes(self._value).decode(errors="replace")


class FfmpegProcess:
    """Uses dedicated readers so FFmpeg cannot block on an unread output pipe."""

    def __init__(self, maximum_output_bytes: int = 256 * 1024) -> None:
        if maximum_output_bytes <= 0:
            raise ValueError("maximum output bytes must be positive")
        self._maximum_output_bytes = maximum_output_bytes
        self._process: subprocess.Popen[bytes] | None = None
        self._arguments: tuple[str, ...] = ()
        self._stdout = _BoundedTextBuffer(maximum_output_bytes)
        self._stderr = _BoundedTextBuffer(maximum_output_bytes)
        self._threads: list[threading.Thread] = []
        self._parser = FfmpegProgressParser()
        self._graceful_stop_requested = False
        self._forced_kill = False

    @property
    def progress(self) -> ProgressSnapshot | None:
        return self._parser.latest

    @property
    def progress_parser(self) -> FfmpegProgressParser:
        return self._parser

    def start(self, arguments: Sequence[str]) -> None:
        if self._process is not None:
            raise ProcessLifecycleError("FFmpeg process is already started")
        if not arguments or not all(
            isinstance(argument, str) and argument for argument in arguments
        ):
            raise ValueError("process arguments must be a non-empty sequence of strings")
        self._arguments = tuple(arguments)
        try:
            self._process = subprocess.Popen(
                self._arguments,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
            )
        except OSError as error:
            raise ProcessLifecycleError(f"unable to start FFmpeg: {error}") from error
        assert self._process.stdout is not None and self._process.stderr is not None
        self._threads = [
            threading.Thread(target=self._read_stdout, args=(self._process.stdout,), daemon=True),
            threading.Thread(target=self._read_stderr, args=(self._process.stderr,), daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def wait(self, timeout_seconds: float | None = None) -> ProcessResult:
        process = self._require_process()
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return self._result(None, timed_out=True)
        self._join_readers()
        return self._result(returncode, timed_out=False)

    def stop(
        self, graceful_timeout_seconds: float = 10, terminate_timeout_seconds: float = 5
    ) -> ProcessResult:
        if graceful_timeout_seconds <= 0 or terminate_timeout_seconds <= 0:
            raise ValueError("stop timeouts must be positive")
        process = self._require_process()
        self._graceful_stop_requested = True
        if process.poll() is None:
            self._signal_group(signal.SIGINT)
        result = self.wait(graceful_timeout_seconds)
        if result.returncode is not None:
            return result
        self._signal_group(signal.SIGTERM)
        result = self.wait(terminate_timeout_seconds)
        if result.returncode is not None:
            return result
        self._forced_kill = True
        self._signal_group(signal.SIGKILL)
        process.wait()
        self._join_readers()
        return self._result(process.returncode, timed_out=False)

    def _read_stdout(self, stream: BinaryIO) -> None:
        for raw_line in stream:
            self._stdout.append(raw_line)
            self._parser.feed_line(raw_line.decode(errors="replace"), time.monotonic())

    def _read_stderr(self, stream: BinaryIO) -> None:
        for raw_line in stream:
            self._stderr.append(raw_line)

    def _signal_group(self, signal_number: int) -> None:
        process = self._require_process()
        try:
            os.killpg(process.pid, signal_number)
        except ProcessLookupError:
            return

    def _join_readers(self) -> None:
        for thread in self._threads:
            thread.join(timeout=1)

    def _result(self, returncode: int | None, *, timed_out: bool) -> ProcessResult:
        return ProcessResult(
            self._arguments,
            returncode,
            self._stdout.text(),
            self._stderr.text(),
            self._graceful_stop_requested,
            self._forced_kill,
            timed_out,
        )

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise ProcessLifecycleError("FFmpeg process was not started")
        return self._process
