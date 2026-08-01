"""Phase 6 power protection, critical-battery, and safe-finalization coverage."""

from __future__ import annotations

import os
import signal
import subprocess
import uuid
from pathlib import Path

import pytest

from usb_cctv_recorder.application.dto import (
    PowerProtectionState,
    PowerSource,
    PowerStatus,
)
from usb_cctv_recorder.domain.states import SessionState
from usb_cctv_recorder.domain.value_objects import SessionId
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request
from usb_cctv_recorder.infrastructure.power.inhibitor import InhibitionError, SystemdInhibitAdapter
from usb_cctv_recorder.infrastructure.power.power_status import LinuxPowerStatusAdapter
from usb_cctv_recorder.worker import main as worker_main
from usb_cctv_recorder.worker.recording import (
    HeadlessRecordingController,
    RecordingFailure,
    StartedRecording,
)
from usb_cctv_recorder.worker.supervisor import WorkerSupervisor


def _request(command: Command) -> Request:
    return Request(command, str(uuid.uuid4()))


class _Process:
    def __init__(self, pid: int, *, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        self.returncode = 0
        return 0


def test_systemd_inhibit_holds_block_delay_and_optional_lid_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    processes = iter((_Process(101), _Process(102)))
    terminated: list[tuple[int, int]] = []

    def popen(arguments: tuple[str, ...], **_kwargs: object) -> _Process:
        calls.append(arguments)
        return next(processes)

    monkeypatch.setattr(os, "killpg", lambda pid, value: terminated.append((pid, value)))
    adapter = SystemdInhibitAdapter(popen)
    adapter.acquire(block_lid_close=True)

    assert adapter.protection_active()
    assert calls[0][1:3] == ("--what=sleep:idle:handle-lid-switch", "--mode=block")
    assert calls[1][1:3] == ("--what=shutdown", "--mode=delay")
    adapter.acquire(block_lid_close=True)
    assert len(calls) == 2
    adapter.release()
    assert not adapter.protection_active()
    assert terminated == [(102, signal.SIGTERM), (101, signal.SIGTERM)]


def test_systemd_inhibit_reports_acquisition_failure_and_detects_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _Process(101)
    monkeypatch.setattr(os, "killpg", lambda _pid, _signal: None)
    calls = 0

    def popen(_arguments: tuple[str, ...], **_kwargs: object) -> _Process:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("logind unavailable")
        return first

    adapter = SystemdInhibitAdapter(popen)
    with pytest.raises(InhibitionError, match="unable to acquire"):
        adapter.acquire(block_lid_close=False)
    assert not adapter.protection_active()

    immediate_exit = SystemdInhibitAdapter(lambda *_args, **_kwargs: _Process(300, returncode=1))
    with pytest.raises(InhibitionError, match="exited before"):
        immediate_exit.acquire(block_lid_close=False)

    stable = SystemdInhibitAdapter(lambda *_args, **_kwargs: _Process(200))
    stable.acquire(block_lid_close=False)
    assert stable.protection_active()
    assert stable._block_process is not None  # The fake represents a lost wrapper process.
    stable._block_process.returncode = 1
    assert not stable.protection_active()


def test_systemd_inhibit_forces_a_stuck_wrapper_process_to_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StuckProcess(_Process):
        def __init__(self) -> None:
            super().__init__(400)
            self.calls = 0

        def wait(self, timeout: float | None = None) -> int:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(("systemd-inhibit",), timeout)
            return super().wait(timeout)

    process = StuckProcess()
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "killpg", lambda pid, value: signals.append((pid, value)))
    SystemdInhibitAdapter._terminate(process)
    assert signals == [(400, signal.SIGTERM), (400, signal.SIGKILL)]


def _supply(root: Path, name: str, supply_type: str, **values: str) -> None:
    directory = root / name
    directory.mkdir()
    (directory / "type").write_text(supply_type)
    for key, value in values.items():
        (directory / key).write_text(value)


def test_linux_power_status_reports_ac_battery_critical_and_unknown(tmp_path: Path) -> None:
    adapter = LinuxPowerStatusAdapter(tmp_path)
    assert adapter.status().source is PowerSource.UNKNOWN

    _supply(tmp_path, "BAT0", "Battery", capacity="6")
    assert adapter.status() == PowerStatus(PowerProtectionState.INACTIVE, PowerSource.BATTERY, 6)
    (tmp_path / "BAT0" / "capacity").write_text("5")
    assert adapter.status().source is PowerSource.CRITICAL_BATTERY

    _supply(tmp_path, "AC", "Mains", online="1")
    assert adapter.status() == PowerStatus(PowerProtectionState.INACTIVE, PowerSource.AC, 5)


class _Inhibitor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.active = False
        self.acquire_calls: list[bool] = []
        self.release_calls = 0

    def acquire(self, *, block_lid_close: bool) -> None:
        self.acquire_calls.append(block_lid_close)
        if self.fail:
            raise InhibitionError("denied")
        self.active = True

    def release(self) -> None:
        self.release_calls += 1
        self.active = False

    def protection_active(self) -> bool:
        return self.active


class _PowerStatus:
    def __init__(self, status: PowerStatus) -> None:
        self.value = status

    def status(self) -> PowerStatus:
        return self.value


class _FinalizingController(HeadlessRecordingController):
    def __init__(self, *, fail_stop: bool = False) -> None:
        self.fail_stop = fail_stop
        self.stop_calls: list[tuple[float, str]] = []
        self.events: list[tuple[str, dict[str, object]]] = []

    def start(self) -> StartedRecording:
        return StartedRecording(SessionId.new(), Path("/tmp/session"), ("ffmpeg",))

    def append_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))

    def stop(
        self, graceful_timeout_seconds: float = 10, *, reason: str = "user_requested"
    ) -> object:
        self.stop_calls.append((graceful_timeout_seconds, reason))
        if self.fail_stop:
            raise RecordingFailure("injected finalization failure")
        return object()

    def poll(self) -> None:
        return None

    def force_stop(self) -> object:
        return object()


def _supervisor(
    controller: _FinalizingController,
    inhibitor: _Inhibitor,
    status: _PowerStatus,
) -> WorkerSupervisor:
    return WorkerSupervisor(
        lambda: controller,
        inhibitor=inhibitor,
        power_status=status,
        prevent_suspend=True,
        block_lid_close=True,
    )


def test_worker_releases_inhibitors_after_safe_stop_and_reports_power_status() -> None:
    controller = _FinalizingController()
    inhibitor = _Inhibitor()
    supervisor = _supervisor(
        controller,
        inhibitor,
        _PowerStatus(PowerStatus(PowerProtectionState.INACTIVE, PowerSource.AC, 80)),
    )

    started = supervisor.handle(_request(Command.START))
    assert started.accepted and started.power_protection == "active"
    assert inhibitor.acquire_calls == [True]
    stopped = supervisor.handle(_request(Command.STOP))
    assert stopped.accepted and stopped.state == "completed"
    assert stopped.power_protection == "inactive"
    assert controller.stop_calls == [(10, "user_requested")]
    assert controller.events == [("finalization_requested", {"reason": "user_requested"})]
    assert inhibitor.release_calls == 1


def test_worker_rejects_inhibition_failure_and_critical_battery_start() -> None:
    controller = _FinalizingController()
    supervisor = _supervisor(
        controller,
        _Inhibitor(fail=True),
        _PowerStatus(PowerStatus(PowerProtectionState.INACTIVE, PowerSource.AC)),
    )
    response = supervisor.handle(_request(Command.START))
    assert not response.accepted and response.error_code == "power_inhibition_unavailable"

    critical = _supervisor(
        controller,
        _Inhibitor(),
        _PowerStatus(PowerStatus(PowerProtectionState.INACTIVE, PowerSource.CRITICAL_BATTERY, 5)),
    )
    response = critical.handle(_request(Command.START))
    assert not response.accepted and response.error_code == "critical_battery"


def test_inhibitor_loss_critical_battery_and_shutdown_finalize_with_known_exit_code() -> None:
    controller = _FinalizingController()
    inhibitor = _Inhibitor()
    source = _PowerStatus(PowerStatus(PowerProtectionState.INACTIVE, PowerSource.BATTERY, 50))
    supervisor = _supervisor(controller, inhibitor, source)
    supervisor.handle(_request(Command.START))
    inhibitor.active = False
    supervisor.poll()
    assert supervisor.state is SessionState.COMPLETED
    assert controller.stop_calls[-1] == (10, "power_inhibition_lost")

    controller = _FinalizingController()
    inhibitor = _Inhibitor()
    source = _PowerStatus(PowerStatus(PowerProtectionState.INACTIVE, PowerSource.BATTERY, 50))
    supervisor = _supervisor(controller, inhibitor, source)
    supervisor.handle(_request(Command.START))
    source.value = PowerStatus(PowerProtectionState.INACTIVE, PowerSource.CRITICAL_BATTERY, 5)
    supervisor.poll()
    assert controller.stop_calls[-1] == (10, "critical_battery")

    controller = _FinalizingController()
    inhibitor = _Inhibitor()
    supervisor = _supervisor(
        controller,
        inhibitor,
        _PowerStatus(PowerStatus(PowerProtectionState.INACTIVE, PowerSource.AC)),
    )
    supervisor.handle(_request(Command.START))
    assert supervisor.finalize_for_shutdown(7) == 0
    assert controller.stop_calls == [(7, "shutdown_requested")]
    assert inhibitor.release_calls == 1


def test_sigterm_runs_worker_shutdown_finalization_before_socket_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    controller = _FinalizingController()
    inhibitor = _Inhibitor()
    supervisor = _supervisor(
        controller,
        inhibitor,
        _PowerStatus(PowerStatus(PowerProtectionState.INACTIVE, PowerSource.AC)),
    )
    assert supervisor.handle(_request(Command.START)).accepted
    handlers: list[object] = []
    closed: list[bool] = []

    class Paths:
        runtime = tmp_path

        def create_private_directories(self) -> None:
            pass

    class Server:
        def __init__(self, _path: Path, _handler: object) -> None:
            pass

        def start(self) -> None:
            pass

        def serve_once(self) -> None:
            handlers[0](signal.SIGTERM, None)  # type: ignore[operator]

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(worker_main, "UnixSocketServer", Server)
    monkeypatch.setattr(worker_main.signal, "getsignal", lambda _signal: "previous")
    monkeypatch.setattr(
        worker_main.signal, "signal", lambda _signal, handler: handlers.append(handler)
    )

    assert worker_main.run_ipc_worker(Paths(), supervisor) == 0  # type: ignore[arg-type]
    assert controller.stop_calls == [(10, "shutdown_requested")]
    assert closed == [True]
    assert handlers[-1] == "previous"


def test_shutdown_failure_records_context_releases_inhibitors_and_returns_error_exit() -> None:
    controller = _FinalizingController(fail_stop=True)
    inhibitor = _Inhibitor()
    supervisor = _supervisor(
        controller,
        inhibitor,
        _PowerStatus(PowerStatus(PowerProtectionState.INACTIVE, PowerSource.AC)),
    )
    assert supervisor.handle(_request(Command.START)).accepted
    assert supervisor.finalize_for_shutdown() == 1
    assert supervisor.state is SessionState.FAILED
    assert controller.events == [("finalization_requested", {"reason": "shutdown_requested"})]
    assert inhibitor.release_calls == 1
