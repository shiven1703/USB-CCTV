"""Phase 5 protocol, socket lifecycle, and worker control coverage."""

from __future__ import annotations

import json
import os
import socket
import stat
import struct
import uuid
from pathlib import Path

import pytest

from usb_cctv_recorder.domain.states import SessionState
from usb_cctv_recorder.domain.value_objects import SessionId
from usb_cctv_recorder.infrastructure.ipc.protocol import (
    MAXIMUM_MESSAGE_BYTES,
    Command,
    ProtocolError,
    Request,
    Response,
    decode,
    encode,
)
from usb_cctv_recorder.infrastructure.ipc.server import SocketLifecycleError, UnixSocketServer
from usb_cctv_recorder.worker.recording import RecordingFailure, StartedRecording
from usb_cctv_recorder.worker.supervisor import WorkerSupervisor


def _request(command: Command = Command.STATUS, command_id: str | None = None) -> Request:
    return Request(command, command_id or str(uuid.uuid4()))


@pytest.mark.parametrize("command", list(Command))
def test_protocol_round_trips_every_supported_request_and_response(command: Command) -> None:
    request = _request(command)
    assert decode(encode(request)) == request
    response = Response(command, request.command_id, "idle", True)
    assert decode(encode(response)) == response


@pytest.mark.parametrize(
    "value, message",
    [
        ({"protocol_version": 2, "command": "status", "command_id": str(uuid.uuid4())}, "version"),
        (
            {"protocol_version": 1, "command": "anything", "command_id": str(uuid.uuid4())},
            "unknown",
        ),
        ({"protocol_version": 1, "command": "status"}, "fields"),
        ({"protocol_version": 1, "command": "status", "command_id": "nope"}, "UUID"),
        (
            {
                "protocol_version": 1,
                "command": "status",
                "command_id": str(uuid.uuid4()),
                "path": "/bin/sh",
            },
            "fields",
        ),
    ],
)
def test_protocol_rejects_versions_unknown_missing_invalid_and_extra_fields(
    value: dict[str, object], message: str
) -> None:
    payload = json.dumps(value).encode()
    with pytest.raises(ProtocolError, match=message):
        decode(len(payload).to_bytes(4, "big") + payload)


def test_protocol_rejects_oversized_frame() -> None:
    with pytest.raises(ProtocolError, match="maximum"):
        decode((MAXIMUM_MESSAGE_BYTES + 1).to_bytes(4, "big"))


@pytest.mark.parametrize(
    "frame, message",
    [
        (b"", "header"),
        ((1).to_bytes(4, "big") + b"{", "JSON"),
        ((1).to_bytes(4, "big") + b"x", "JSON"),
        ((2).to_bytes(4, "big") + b"[]", "object"),
    ],
)
def test_protocol_rejects_malformed_frames(frame: bytes, message: str) -> None:
    with pytest.raises(ProtocolError, match=message):
        decode(frame)


def test_protocol_rejects_invalid_response_fields() -> None:
    value = Response(Command.STATUS, str(uuid.uuid4()), "idle", True).to_mapping()
    value["accepted"] = "yes"
    payload = json.dumps(value).encode()
    with pytest.raises(ProtocolError, match="boolean"):
        decode(len(payload).to_bytes(4, "big") + payload)

    value = Response(Command.STATUS, str(uuid.uuid4()), "idle", True).to_mapping()
    value["command"] = "unknown"
    payload = json.dumps(value).encode()
    with pytest.raises(ProtocolError, match="unknown response"):
        decode(len(payload).to_bytes(4, "big") + payload)

    value = Response(Command.STATUS, str(uuid.uuid4()), "idle", True).to_mapping()
    value["state"] = ""
    payload = json.dumps(value).encode()
    with pytest.raises(ProtocolError, match="state"):
        decode(len(payload).to_bytes(4, "big") + payload)


def test_protocol_rejects_frame_length_mismatch_and_oversized_serialization() -> None:
    with pytest.raises(ProtocolError, match="length"):
        decode((2).to_bytes(4, "big") + b"{}x")

    class OversizedMessage:
        def to_mapping(self) -> dict[str, str]:
            return {"payload": "x" * MAXIMUM_MESSAGE_BYTES}

    with pytest.raises(ProtocolError, match="maximum"):
        encode(OversizedMessage())  # type: ignore[arg-type]


def test_socket_is_private_and_rejects_stale_unsafe_paths(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "worker.sock"
    server = UnixSocketServer(
        path, lambda request: Response(request.command, request.command_id, "idle", True)
    )
    server.start()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    server.close()

    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text("not a socket")
    with pytest.raises(SocketLifecycleError, match="unsafe"):
        server.start()
    path.unlink()

    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(os.fspath(path))
    stale.close()
    server.start()
    assert path.is_socket()
    server.close()


def test_socket_timeout_handler_failure_and_access_guards(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "worker.sock"

    def failing_handler(request: Request) -> Response:
        raise RuntimeError(request.command_id)

    server = UnixSocketServer(path, failing_handler)
    with pytest.raises(SocketLifecycleError, match="not running"):
        server.serve_once()
    server.start()
    assert not server.serve_once()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(os.fspath(path))
        client.sendall(encode(_request()))
        assert server.serve_once()
    server.close()
    server.close()

    class OtherUserConnection:
        def getsockopt(self, level: int, option: int, size: int) -> bytes:
            assert (level, option, size) == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            return struct.pack("3i", 1, os.getuid() + 1, 1)

    assert not server._peer_is_current_user(OtherUserConnection())  # type: ignore[arg-type]

    path.parent.mkdir(mode=0o755, exist_ok=True)
    path.parent.chmod(0o755)
    with pytest.raises(SocketLifecycleError, match="private"):
        UnixSocketServer(
            path, lambda request: Response(request.command, request.command_id, "idle", True)
        ).start()


class _Controller:
    def __init__(self, *, fails_start: bool = False, crashes: bool = False) -> None:
        self.fails_start = fails_start
        self.crashes = crashes
        self.start_count = 0
        self.stop_count = 0
        self.force_stop_count = 0

    def start(self) -> StartedRecording:
        self.start_count += 1
        if self.fails_start:
            raise RecordingFailure("start failure")
        return StartedRecording(SessionId.new(), Path("/tmp/session"), ("ffmpeg",))

    def stop(self) -> object:
        self.stop_count += 1
        return object()

    def force_stop(self) -> object:
        self.force_stop_count += 1
        return object()

    def poll(self) -> None:
        if self.crashes:
            raise RecordingFailure("crash")
        return None


def test_worker_status_start_safe_stop_idempotency_second_start_and_force_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    controller = _Controller()
    supervisor = WorkerSupervisor(lambda: controller)  # type: ignore[arg-type]

    assert supervisor.handle(_request()).state == "idle"
    started = supervisor.handle(_request(Command.START))
    assert started.accepted and started.state == "recording_av"
    assert supervisor.handle(_request(Command.START)).state == "recording_av"
    assert controller.start_count == 1
    stop = _request(Command.STOP)
    assert supervisor.handle(stop).state == "completed"
    assert supervisor.handle(stop).state == "completed"
    assert controller.stop_count == 1

    controller = _Controller()
    supervisor = WorkerSupervisor(lambda: controller)  # type: ignore[arg-type]
    supervisor.handle(_request(Command.START))
    assert supervisor.handle(_request(Command.FORCE_STOP)).state == "failed"
    assert controller.force_stop_count == 1
    assert "last-resort force-stop" in caplog.text


def test_worker_retry_and_process_crash_state() -> None:
    controllers = iter((_Controller(fails_start=True), _Controller()))
    supervisor = WorkerSupervisor(lambda: next(controllers))  # type: ignore[arg-type]
    assert supervisor.handle(_request(Command.START)).state == "failed"
    assert supervisor.handle(_request(Command.RETRY)).state == "recording_av"

    crashed = _Controller(crashes=True)
    supervisor = WorkerSupervisor(lambda: crashed)  # type: ignore[arg-type]
    supervisor.handle(_request(Command.START))
    supervisor.poll()
    assert supervisor.state is SessionState.FAILED


def test_worker_rejects_incompatible_duplicate_command_id() -> None:
    supervisor = WorkerSupervisor()
    identifier = str(uuid.uuid4())
    assert supervisor.handle(_request(Command.STATUS, identifier)).accepted
    response = supervisor.handle(_request(Command.START, identifier))
    assert not response.accepted
    assert response.error_code == "command_id_conflict"


def test_worker_reports_unconfigured_start_and_retry_unavailability() -> None:
    supervisor = WorkerSupervisor()
    start = supervisor.handle(_request(Command.START))
    assert not start.accepted and start.error_code == "recording_configuration_unavailable"
    retry = supervisor.handle(_request(Command.RETRY))
    assert not retry.accepted and retry.error_code == "retry_not_available"
    force = supervisor.handle(_request(Command.FORCE_STOP))
    assert not force.accepted and force.error_code == "no_active_recording"
