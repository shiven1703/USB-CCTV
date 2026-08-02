"""Synthetic Phase 5 worker flow without a physical capture device."""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import pytest

from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    build_synthetic_recording_command,
)
from usb_cctv_recorder.infrastructure.ipc.client import UnixSocketClient
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request
from usb_cctv_recorder.infrastructure.ipc.server import UnixSocketServer
from usb_cctv_recorder.worker.recording import HeadlessRecordingController
from usb_cctv_recorder.worker.supervisor import WorkerSupervisor


def _request(command: Command) -> Request:
    return Request(command, str(uuid.uuid4()))


def test_synthetic_recording_survives_client_reconnect_and_stops_safely(tmp_path: Path) -> None:
    socket_path = tmp_path / "runtime" / "worker.sock"

    def factory() -> HeadlessRecordingController:
        return HeadlessRecordingController(
            tmp_path / "media",
            lambda pattern: build_synthetic_recording_command(
                pattern, 60, duration_seconds=30, realtime=True
            ),
        )

    supervisor = WorkerSupervisor(factory)
    server = UnixSocketServer(socket_path, supervisor.handle)
    try:
        server.start()
    except PermissionError as error:
        pytest.skip(f"test sandbox does not permit Unix-domain sockets: {error}")
    running = True

    def serve() -> None:
        while running:
            try:
                server.serve_once()
            except OSError:
                return
            supervisor.poll()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        first_client = UnixSocketClient(socket_path)
        assert first_client.request(_request(Command.STATUS)).state == "idle"
        started = first_client.request(_request(Command.START))
        assert started.accepted and started.state == "recording_av"
        # A reopened GUI/client only reconnects and queries; it does not own or stop FFmpeg.
        second_client = UnixSocketClient(socket_path)
        assert second_client.request(_request(Command.STATUS)).state == "recording_av"
        # FFmpeg needs to finish installing its signal handlers before a graceful stop.
        time.sleep(0.6)
        stopped = second_client.request(_request(Command.STOP))
        assert stopped.accepted and stopped.state == "completed"
    finally:
        running = False
        server.close()
        thread.join(timeout=2)

    deadline = time.monotonic() + 2
    while not list((tmp_path / "media").glob("originals/*/session-*/segment-*.mkv")):
        assert time.monotonic() < deadline
        time.sleep(0.05)
