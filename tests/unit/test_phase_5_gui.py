"""Phase 5 GUI reconnect behaviour stays separate from worker control."""

from __future__ import annotations

import uuid

import pytest

from usb_cctv_recorder.application.dto import DeviceDiscovery
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Response
from usb_cctv_recorder.presentation.qt.main_window import (
    DeviceProbeThread,
    MainWindow,
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
