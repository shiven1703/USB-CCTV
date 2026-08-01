"""Phase 5 static user-unit and systemctl adapter coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from usb_cctv_recorder.application.configuration import WorkerRecordingConfiguration
from usb_cctv_recorder.infrastructure.commands.runner import CommandResult
from usb_cctv_recorder.infrastructure.systemd.user_service import (
    UNIT_NAME,
    SystemdUserService,
    SystemdUserServiceError,
)
from usb_cctv_recorder.worker import main as worker_main


class _Runner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: tuple[str, ...]) -> CommandResult:
        self.calls.append(arguments)
        return self.result


def test_user_service_has_bounded_failure_restart_and_private_runtime_directory() -> None:
    unit = (Path(__file__).parents[2] / "systemd" / UNIT_NAME).read_text()
    assert "Type=exec" in unit
    assert "ExecStart=/usr/bin/usb-cctv-recorder --worker" in unit
    assert "Restart=on-failure" in unit
    assert "RestartSec=5" in unit
    assert "TimeoutStopSec=40s" in unit
    assert "StartLimitIntervalSec=60" in unit and "StartLimitBurst=3" in unit
    assert "RuntimeDirectory=usb-cctv-recorder" in unit and "RuntimeDirectoryMode=0700" in unit
    assert "UMask=0077" in unit


def test_service_adapter_uses_structured_systemctl_and_surfaces_manager_failures() -> None:
    success = CommandResult((), 0, "", "")
    runner = _Runner(success)
    service = SystemdUserService(runner)  # type: ignore[arg-type]
    service.start_worker()
    service.stop_worker()
    assert runner.calls == [
        ("systemctl", "--user", "start", UNIT_NAME),
        ("systemctl", "--user", "stop", UNIT_NAME),
    ]
    failing = _Runner(CommandResult((), 1, "", "manager unavailable"))
    with pytest.raises(SystemdUserServiceError, match="manager unavailable"):
        SystemdUserService(failing).start_worker()  # type: ignore[arg-type]


def test_ipc_worker_creates_runtime_socket_and_cleans_up_on_interrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Paths:
        runtime = tmp_path

        def create_private_directories(self) -> None:
            pass

    created: list[object] = []
    signal_handlers: list[object] = []

    class Server:
        def __init__(self, path: Path, handler: object) -> None:
            assert path == tmp_path / "worker.sock"
            created.append(handler)

        def start(self) -> None:
            pass

        def serve_once(self) -> None:
            signal_handlers[0](15, None)  # type: ignore[operator]

        def close(self) -> None:
            created.append("closed")

    monkeypatch.setattr(worker_main, "UnixSocketServer", Server)
    monkeypatch.setattr(worker_main, "_recording_factory", lambda _: None)
    monkeypatch.setattr(worker_main.signal, "getsignal", lambda _: "previous")
    monkeypatch.setattr(
        worker_main.signal, "signal", lambda _, handler: signal_handlers.append(handler)
    )
    assert worker_main.run_ipc_worker(Paths()) == 0  # type: ignore[arg-type]
    assert created[-1] == "closed"
    assert signal_handlers[-1] == "previous"


def test_worker_builds_a_recording_factory_only_from_private_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configuration = WorkerRecordingConfiguration(
        tmp_path / "media",
        "/dev/v4l/by-id/camera",
        "alsa_input.camera",
        2560,
        1440,
        30,
        15,
        60,
    )

    class Store:
        def __init__(self, paths: object) -> None:
            assert paths is sentinel

        def load(self) -> WorkerRecordingConfiguration | None:
            return configuration

    sentinel = object()
    monkeypatch.setattr(worker_main, "WorkerConfigurationStore", Store)
    assert worker_main._recording_factory(sentinel) is not None  # type: ignore[arg-type]


def test_worker_builds_ffmpeg_arguments_from_persisted_configuration_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configuration = WorkerRecordingConfiguration(
        tmp_path / "media",
        "/dev/v4l/by-id/camera",
        "alsa_input.camera",
        2560,
        1440,
        30,
        15,
        60,
    )

    class PersistentPath:
        def resolve(self, strict: bool) -> Path:
            assert strict
            return tmp_path / "video2"

    monkeypatch.setattr(worker_main, "Path", lambda _: PersistentPath())
    controller = worker_main._configured_controller(configuration)
    arguments = controller._command_factory(tmp_path / "segment-%06d.mkv")  # type: ignore[attr-defined]
    assert "/dev/v4l/by-id/camera" not in arguments
    assert str(tmp_path / "video2") in arguments
    assert "alsa_input.camera" in arguments
