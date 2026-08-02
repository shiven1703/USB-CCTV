"""Phase 5 GUI reconnect behaviour stays separate from worker control."""

from __future__ import annotations

import uuid

import pytest

from usb_cctv_recorder.application.dto import DeviceDiscovery
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Response
from usb_cctv_recorder.presentation.qt.main_window import (
    DeviceProbeThread,
    MainWindow,
    WorkerCommandThread,
    WorkerStatusThread,
)


class _Client:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.requests: list[object] = []

    def request(self, request: object) -> Response:
        self.requests.append(request)
        return self.response


def test_gui_reconnects_to_existing_worker_and_close_sends_no_stop(qtbot: pytest.QtBot) -> None:
    client = _Client(
        Response(Command.STATUS, str(uuid.uuid4()), "recording_av", True, session_id="s1")
    )
    window = MainWindow(worker_client_factory=lambda: client)  # type: ignore[arg-type]
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: "recording_av" in window.statusBar().currentMessage(), timeout=2_000)
    assert "recording_av" in window.statusBar().currentMessage()
    window.close()
    assert len(client.requests) == 1


def test_worker_status_thread_reports_unavailable_worker(qtbot: pytest.QtBot) -> None:
    class FailingClient:
        def request(self, request: object) -> Response:
            raise OSError("missing")

    thread = WorkerStatusThread(lambda: FailingClient())  # type: ignore[arg-type]
    with qtbot.waitSignal(thread.failed, timeout=2_000) as result:
        thread.start()
    assert result.args == ["missing"]


def test_status_and_probe_thread_handlers_are_directly_observable(qtbot: pytest.QtBot) -> None:
    client = _Client(Response(Command.STATUS, str(uuid.uuid4()), "idle", True))
    status = WorkerStatusThread(lambda: client)
    statuses: list[object] = []
    status.completed.connect(statuses.append)
    status.run()
    assert statuses

    class Service:
        def discover(self) -> DeviceDiscovery:
            return DeviceDiscovery((), ())

    probe = DeviceProbeThread(Service())  # type: ignore[arg-type]
    discoveries: list[object] = []
    probe.completed.connect(discoveries.append)
    probe.run()
    assert discoveries

    window = MainWindow()
    qtbot.addWidget(window)
    window._discovery_completed(DeviceDiscovery((), ()))
    window._worker_status_completed(
        Response(
            Command.STATUS,
            str(uuid.uuid4()),
            "recovering",
            True,
            video_health="stalled",
            audio_health="healthy",
            output_health="warning",
            recovery_attempt=2,
            last_gap_seconds=3.5,
        )
    )
    assert "video: stalled" in window.statusBar().currentMessage()
    assert window._retry_button.isEnabled()
    window._worker_status_failed("missing")
    assert "unavailable" in window.statusBar().currentMessage()


def test_retry_now_runs_only_the_closed_retry_command_off_the_gui_thread(
    qtbot: pytest.QtBot,
) -> None:
    client = _Client(Response(Command.RETRY, str(uuid.uuid4()), "recovering", True))
    window = MainWindow(worker_client_factory=lambda: client)  # type: ignore[arg-type]
    qtbot.addWidget(window)
    window._worker_status_completed(Response(Command.STATUS, str(uuid.uuid4()), "recovering", True))
    window._retry_now()
    qtbot.waitUntil(
        lambda: any(getattr(request, "command") is Command.RETRY for request in client.requests),
        timeout=2_000,
    )
    request = next(
        request for request in client.requests if getattr(request, "command") is Command.RETRY
    )
    assert getattr(request, "command") is Command.RETRY
    window._worker_command_thread.wait(2_000)  # type: ignore[union-attr]


def test_worker_command_thread_reports_worker_failure(qtbot: pytest.QtBot) -> None:
    from usb_cctv_recorder.presentation.qt.main_window import WorkerCommandThread

    class FailingClient:
        def request(self, request: object) -> Response:
            raise OSError("missing")

    thread = WorkerCommandThread(lambda: FailingClient(), Command.RETRY)  # type: ignore[arg-type]
    with qtbot.waitSignal(thread.failed, timeout=2_000) as result:
        thread.start()
    assert result.args == ["missing"]


def test_setup_start_button_controls_the_static_worker_through_closed_ipc(
    qtbot: pytest.QtBot,
) -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def request(self, request: object) -> Response:
            self.requests.append(request)
            command = getattr(request, "command")
            state = "recording_av" if command is Command.START else "completed"
            return Response(command, str(uuid.uuid4()), state, True)

    class Service:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def start_worker(self) -> None:
            self.calls.append("start")

        def stop_worker(self) -> None:
            self.calls.append("stop")

    client = RecordingClient()
    service = Service()
    window = MainWindow(
        worker_client_factory=lambda: client,  # type: ignore[arg-type]
        worker_service=service,  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    window.setup_page.start_button.setEnabled(True)

    window._toggle_recording()
    qtbot.waitUntil(
        lambda: service.calls == ["start"]
        and window.setup_page.start_button.text() == "Stop safely"
    )

    window._toggle_recording()
    qtbot.waitUntil(
        lambda: service.calls == ["start", "stop"]
        and window.setup_page.start_button.text() == "Start"
    )
    assert [
        getattr(item, "command")
        for item in client.requests
        if getattr(item, "command") in {Command.START, Command.STOP}
    ] == [
        Command.START,
        Command.STOP,
    ]


def test_worker_command_thread_starts_and_stops_the_static_service_before_and_after_ipc() -> None:
    class Client:
        def __init__(self) -> None:
            self.commands: list[Command] = []

        def request(self, request: object) -> Response:
            command = getattr(request, "command")
            self.commands.append(command)
            return Response(command, str(uuid.uuid4()), "completed", True)

    class Service:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def start_worker(self) -> None:
            self.calls.append("start")

        def stop_worker(self) -> None:
            self.calls.append("stop")

    client = Client()
    service = Service()
    responses: list[Response] = []
    start = WorkerCommandThread(lambda: client, Command.START, service)  # type: ignore[arg-type]
    start.completed.connect(responses.append)
    start.run()
    stop = WorkerCommandThread(lambda: client, Command.STOP, service)  # type: ignore[arg-type]
    stop.completed.connect(responses.append)
    stop.run()

    assert client.commands == [Command.START, Command.STOP]
    assert service.calls == ["start", "stop"]
    assert [response.command for response in responses] == [Command.START, Command.STOP]


def test_start_command_retries_until_the_new_worker_socket_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.attempts = 0

        def request(self, request: object) -> Response:
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("socket not ready")
            return Response(getattr(request, "command"), str(uuid.uuid4()), "recording_av", True)

    client = Client()
    thread = WorkerCommandThread(lambda: client, Command.START)  # type: ignore[arg-type]
    responses: list[Response] = []
    thread.completed.connect(responses.append)
    monkeypatch.setattr("usb_cctv_recorder.presentation.qt.main_window.time.sleep", lambda _: None)

    thread.run()

    assert client.attempts == 2
    assert responses[0].state == "recording_av"


def test_worker_command_failure_and_stale_initial_status_do_not_override_recording(
    qtbot: pytest.QtBot,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    recording = Response(Command.START, str(uuid.uuid4()), "recording_av", True)
    window._worker_status_completed(recording)
    assert window.setup_page.start_button.text() == "Stop safely"

    window._worker_command_thread = object()  # type: ignore[assignment]
    window._initial_worker_status_completed(
        Response(Command.STATUS, str(uuid.uuid4()), "idle", True)
    )
    window._initial_worker_status_failed("missing")
    assert window.setup_page.start_button.text() == "Stop safely"

    window._worker_command_thread = None
    window._worker_command_failed("manager unavailable")
    assert window.setup_page.start_button.text() == "Start"
    assert "manager unavailable" in window.statusBar().currentMessage()
