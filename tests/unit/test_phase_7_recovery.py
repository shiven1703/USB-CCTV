"""Phase 7 watchdog, hotplug, recovery evidence, and degraded-mode coverage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

from usb_cctv_recorder.domain.states import HealthState, SessionState
from usb_cctv_recorder.domain.value_objects import SessionId
from usb_cctv_recorder.infrastructure.devices import hotplug
from usb_cctv_recorder.infrastructure.devices.hotplug import (
    UdevVideoHotplugMonitor,
    VideoDeviceEvent,
    parse_udevadm_events,
    resolve_video_identity,
)
from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    build_synthetic_recording_command,
)
from usb_cctv_recorder.infrastructure.ffmpeg.progress_parser import ProgressHealth, ProgressSnapshot
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request
from usb_cctv_recorder.infrastructure.persistence.recovery_journal import (
    RecoveryGap,
    RecoveryJournal,
    RecoveryJournalStore,
)
from usb_cctv_recorder.worker.recording import RecordingFailure, StartedRecording
from usb_cctv_recorder.worker.supervisor import WorkerSupervisor
from usb_cctv_recorder.worker.watchdog import CaptureWatchdog, RecoveryReason, RetrySchedule


def _request(command: Command) -> Request:
    return Request(command, str(uuid.uuid4()))


@pytest.mark.parametrize("attempt, delay", [(1, 2), (2, 5), (3, 10), (4, 30), (5, 60), (6, 60)])
def test_retry_schedule_is_bounded_and_exact(attempt: int, delay: int) -> None:
    assert RetrySchedule.delay_for_attempt(attempt) == delay
    with pytest.raises(ValueError, match="positive"):
        RetrySchedule.delay_for_attempt(0)


def test_watchdog_uses_each_progress_signal_and_monotonic_thresholds() -> None:
    watchdog = CaptureWatchdog()
    progress = ProgressSnapshot(10, 100, 1.0, 1.0, ProgressHealth.HEALTHY, False)
    health = watchdog.observe(progress, 100, 10)
    assert (health.video, health.audio, health.output) == (HealthState.HEALTHY,) * 3
    warning = watchdog.observe(progress, 100, 15)
    assert (warning.video, warning.audio, warning.output) == (HealthState.WARNING,) * 3
    stalled = watchdog.observe(progress, 100, 25)
    assert CaptureWatchdog.recovery_reason(stalled) is RecoveryReason.VIDEO_STALLED
    advanced = ProgressSnapshot(11, 101, 2.0, 1.0, ProgressHealth.HEALTHY, False)
    healthy = watchdog.observe(advanced, 101, 26)
    assert (healthy.video, healthy.audio, healthy.output) == (HealthState.HEALTHY,) * 3


def test_armed_watchdog_stalls_a_live_process_that_never_emits_progress() -> None:
    watchdog = CaptureWatchdog()
    watchdog.arm(10)
    assert watchdog.observe(None, None, 14).video is HealthState.HEALTHY
    assert watchdog.observe(None, None, 15).audio is HealthState.WARNING
    assert watchdog.observe(None, None, 25).output is HealthState.STALLED


def test_watchdog_distinguishes_live_process_video_audio_and_output_stalls() -> None:
    initial = ProgressSnapshot(1, 1, 1.0, None, ProgressHealth.HEALTHY, False)

    video = CaptureWatchdog()
    video.observe(initial, 1, 0)
    video_stall = video.observe(
        ProgressSnapshot(1, 2, 16.0, None, ProgressHealth.HEALTHY, False), 2, 16
    )
    assert CaptureWatchdog.recovery_reason(video_stall) is RecoveryReason.VIDEO_STALLED

    audio = CaptureWatchdog()
    audio.observe(initial, 1, 0)
    audio_stall = audio.observe(
        ProgressSnapshot(16, 2, 1.0, None, ProgressHealth.HEALTHY, False), 2, 16
    )
    assert CaptureWatchdog.recovery_reason(audio_stall) is RecoveryReason.AUDIO_STALLED

    output = CaptureWatchdog()
    output.observe(initial, 1, 0)
    output_stall = output.observe(
        ProgressSnapshot(16, 1, 16.0, None, ProgressHealth.HEALTHY, False), 1, 16
    )
    assert CaptureWatchdog.recovery_reason(output_stall) is RecoveryReason.OUTPUT_STALLED


def test_udev_property_parser_discards_non_video_events() -> None:
    events = parse_udevadm_events(
        "ACTION=remove\nSUBSYSTEM=video4linux\nDEVNAME=/dev/video9\n\n"
        "ACTION=add\nSUBSYSTEM=block\nDEVNAME=/dev/sda\n\n"
    )
    assert len(events) == 1
    assert (events[0].action, events[0].device_path) == ("remove", "/dev/video9")


def test_udev_monitor_uses_documented_arguments_reads_events_and_closes() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    class Process:
        def __init__(self) -> None:
            self.stdout = StringIO("ACTION=add\nSUBSYSTEM=video4linux\nDEVNAME=/dev/video17\n\n")
            self.terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

    process = Process()

    def popen(arguments: tuple[str, ...], **kwargs: object) -> Process:
        calls.append((arguments, kwargs))
        return process

    monitor = UdevVideoHotplugMonitor(popen)  # type: ignore[arg-type]
    monitor.start()
    monitor.start()
    for _ in range(20):
        events = monitor.poll()
        if events:
            break
    else:
        pytest.fail("monitor reader did not enqueue the udev event")
    assert events[0].device_path == "/dev/video17"
    assert calls == [
        (
            ("udevadm", "monitor", "--udev", "--property", "--subsystem-match=video4linux"),
            {
                "stdin": hotplug.subprocess.DEVNULL,
                "stdout": hotplug.subprocess.PIPE,
                "stderr": hotplug.subprocess.DEVNULL,
                "text": True,
                "shell": False,
            },
        )
    ]
    monitor.close()
    assert process.terminated


def test_video_identity_resolution_requires_the_selected_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = Path("/dev/video17")

    class Alias:
        def resolve(self, *, strict: bool) -> Path:
            assert strict
            return target

    monkeypatch.setattr(hotplug, "Path", lambda _value: Alias())
    assert resolve_video_identity("/dev/v4l/by-id/selected-video-index0") == target
    with pytest.raises(ValueError, match="persistent"):
        resolve_video_identity("/dev/video2")


def test_recovery_journal_atomically_records_gap_facts(tmp_path: Path) -> None:
    store = RecoveryJournalStore()
    path = tmp_path / "recovery.json"
    store.save(
        path,
        RecoveryJournal(
            "recovering",
            2,
            15.0,
            (
                RecoveryGap(
                    "video_disconnected",
                    "2026-08-02T10:00:00+00:00",
                    "2026-08-02T10:00:12+00:00",
                    3.0,
                    12.0,
                    2,
                    1.0,
                    2.0,
                ),
            ),
        ),
    )
    content = path.read_text()
    assert '"duration_seconds":12.0' in content
    assert '"reason":"video_disconnected"' in content
    assert not list(tmp_path.glob("*.tmp"))


def test_synthetic_emergency_commands_never_add_filler_streams(tmp_path: Path) -> None:
    audio = build_synthetic_recording_command(tmp_path / "audio-%06d.mkv", 1, include_video=False)
    video = build_synthetic_recording_command(tmp_path / "video-%06d.mkv", 1, include_audio=False)
    assert "testsrc2=size=320x240:rate=10" not in audio
    assert "sine=frequency=1000:sample_rate=48000" not in video
    assert "0:a:0" in audio and "0:v:0" in video


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value


class _RecoveringController:
    def __init__(self, directory: Path) -> None:
        self.session_directory = directory
        self.is_running = False
        self.progress = None
        self.events: list[tuple[str, dict[str, object]]] = []
        self.resumed: list[SessionState] = []
        self.stopped = 0

    def start(self) -> StartedRecording:
        return StartedRecording(SessionId.new(), self.session_directory, ("ffmpeg",))

    def begin_recovery(self, _reason: str) -> bool:
        return True

    def resume_after_recovery(self, state: SessionState) -> None:
        self.resumed.append(state)
        self.is_running = True

    def append_event(self, event: str, payload: dict[str, object]) -> None:
        self.events.append((event, payload))

    def active_output_bytes(self) -> int | None:
        return None

    def poll(self) -> None:
        return None

    def stop(self, *_args: object, **_kwargs: object) -> object:
        self.stopped += 1
        return object()

    def force_stop(self) -> object:
        return object()


class _Hotplug:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.events: list[VideoDeviceEvent] = []

    def start(self) -> None:
        self.started = True

    def poll(self) -> tuple[VideoDeviceEvent, ...]:
        values = tuple(self.events)
        self.events.clear()
        return values

    def close(self) -> None:
        self.closed = True


def test_ffmpeg_exit_creates_exact_gap_new_recovery_segment_and_retry_now(tmp_path: Path) -> None:
    clock = _Clock()
    controller = _RecoveringController(tmp_path)
    supervisor = WorkerSupervisor(
        lambda: controller,  # type: ignore[arg-type]
        monotonic=clock.monotonic,
        wall_clock=lambda: datetime(2026, 8, 2, tzinfo=UTC),
    )
    assert supervisor.handle(_request(Command.START)).state == "recording_av"
    supervisor.poll()
    status = supervisor.handle(_request(Command.STATUS))
    assert status.state == "recovering"
    assert status.retry_in_seconds == 2
    clock.value = 2
    assert supervisor.handle(_request(Command.RETRY)).state == "recording_av"
    assert controller.resumed == [SessionState.RECORDING_AV]
    resumed = supervisor.handle(_request(Command.STATUS))
    assert (resumed.video_health, resumed.audio_health, resumed.output_health) == (
        "unknown",
        "unknown",
        "unknown",
    )
    supervisor.poll()
    assert supervisor.state is SessionState.RECORDING_AV
    assert supervisor.handle(_request(Command.STATUS)).last_gap_seconds == 2
    assert (tmp_path / "recovery.json").exists()
    assert any(event == "capture_gap_ended" for event, _ in controller.events)


def test_stop_during_recovery_cancels_the_retry_path(tmp_path: Path) -> None:
    clock = _Clock()
    controller = _RecoveringController(tmp_path)
    hotplug = _Hotplug()
    supervisor = WorkerSupervisor(  # type: ignore[arg-type]
        lambda: controller, monotonic=clock.monotonic, hotplug_monitor=hotplug
    )
    supervisor.handle(_request(Command.START))
    supervisor.poll()
    assert supervisor.state is SessionState.RECOVERING
    assert supervisor.handle(_request(Command.STOP)).state == "completed"
    clock.value = 60
    supervisor.poll()
    assert not controller.resumed
    assert hotplug.closed


def test_device_return_under_a_new_video_node_reuses_only_the_persistent_identity(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    controller = _RecoveringController(tmp_path)
    controller.is_running = True
    hotplug = _Hotplug()
    resolutions = iter((None, Path("/dev/video17")))
    supervisor = WorkerSupervisor(
        lambda: controller,  # type: ignore[arg-type]
        hotplug_monitor=hotplug,  # type: ignore[arg-type]
        camera_identity="/dev/v4l/by-id/selected-camera-video-index0",
        video_identity_resolver=lambda _identity: next(resolutions),
        monotonic=clock.monotonic,
    )
    supervisor.handle(_request(Command.START))
    hotplug.events.append(VideoDeviceEvent("remove", "/dev/video2", {}))
    supervisor.poll()
    assert supervisor.state is SessionState.RECOVERING
    clock.value = 2
    supervisor.poll()
    assert controller.resumed == [SessionState.RECORDING_AV]


def test_video_return_promotes_audio_only_capture_to_a_new_av_segment(tmp_path: Path) -> None:
    clock = _Clock()
    controller = _RecoveringController(tmp_path)
    controller.is_running = True
    hotplug = _Hotplug()
    supervisor = WorkerSupervisor(
        lambda: controller,  # type: ignore[arg-type]
        hotplug_monitor=hotplug,  # type: ignore[arg-type]
        camera_identity="/dev/v4l/by-id/selected-camera-video-index0",
        video_identity_resolver=lambda _identity: Path("/dev/video17"),
        monotonic=clock.monotonic,
    )
    supervisor.handle(_request(Command.START))
    supervisor._state = SessionState.RECORDING_AUDIO_ONLY
    hotplug.events.append(VideoDeviceEvent("add", "/dev/video17", {}))
    supervisor.poll()
    assert supervisor.state is SessionState.RECOVERING
    clock.value = 2
    supervisor.poll()
    assert controller.resumed == [SessionState.RECORDING_AV]


def test_five_repeated_disconnect_reconnect_cycles_remain_in_bounded_recovery(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    controller = _RecoveringController(tmp_path)
    supervisor = WorkerSupervisor(lambda: controller, monotonic=clock.monotonic)  # type: ignore[arg-type]
    supervisor.handle(_request(Command.START))
    for _ in range(5):
        controller.is_running = False
        supervisor.poll()
        assert supervisor.state is SessionState.RECOVERING
        clock.value += 2
        supervisor.poll()
        assert supervisor.state is SessionState.RECORDING_AV
    assert controller.resumed == [SessionState.RECORDING_AV] * 5


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (
            ProgressSnapshot(1, 1, 1.0, None, ProgressHealth.HEALTHY, False),
            ProgressSnapshot(1, 2, 16.0, None, ProgressHealth.HEALTHY, False),
            SessionState.RECORDING_AUDIO_ONLY,
        ),
        (
            ProgressSnapshot(1, 1, 1.0, None, ProgressHealth.HEALTHY, False),
            ProgressSnapshot(16, 2, 1.0, None, ProgressHealth.HEALTHY, False),
            SessionState.RECORDING_VIDEO_ONLY,
        ),
    ],
)
def test_live_watchdog_stalls_start_the_correct_degraded_mode(
    tmp_path: Path,
    first: ProgressSnapshot,
    second: ProgressSnapshot,
    expected: SessionState,
) -> None:
    clock = _Clock()
    controller = _RecoveringController(tmp_path)
    controller.is_running = True
    controller.progress = first
    supervisor = WorkerSupervisor(lambda: controller, monotonic=clock.monotonic)  # type: ignore[arg-type]
    supervisor.handle(_request(Command.START))
    supervisor.poll()
    clock.value = 16
    controller.progress = second
    supervisor.poll()
    assert supervisor.state is SessionState.RECOVERING
    supervisor.handle(_request(Command.RETRY))
    assert controller.resumed == [expected]


def test_failed_recovery_attempt_uses_next_bounded_delay(tmp_path: Path) -> None:
    class FailingController(_RecoveringController):
        def resume_after_recovery(self, state: SessionState) -> None:
            raise RecordingFailure(state.value)

    clock = _Clock()
    controller = FailingController(tmp_path)
    supervisor = WorkerSupervisor(lambda: controller, monotonic=clock.monotonic)  # type: ignore[arg-type]
    supervisor.handle(_request(Command.START))
    supervisor.poll()
    clock.value = 2
    supervisor.poll()
    response = supervisor.handle(_request(Command.STATUS))
    assert response.state == "recovering"
    assert response.recovery_attempt == 1
    assert response.retry_in_seconds == 5
