"""Worker-owned recording control exposed through the closed IPC protocol."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime

from usb_cctv_recorder.application.dto import (
    PowerProtectionState,
    PowerSource,
    PowerStatus,
)
from usb_cctv_recorder.application.ports import PowerInhibitorPort, PowerStatusPort
from usb_cctv_recorder.application.storage import StorageGovernorPort
from usb_cctv_recorder.domain.states import HealthState, SessionState
from usb_cctv_recorder.infrastructure.devices.hotplug import (
    UdevVideoHotplugMonitor,
    resolve_video_identity,
)
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request, Response
from usb_cctv_recorder.infrastructure.persistence.recovery_journal import (
    RecoveryGap,
    RecoveryJournal,
    RecoveryJournalStore,
)
from usb_cctv_recorder.infrastructure.power.inhibitor import InhibitionError

from .recording import HeadlessRecordingController, RecordingFailure, StartedRecording
from .watchdog import CaptureHealth, CaptureWatchdog, RecoveryReason, RetrySchedule

LOGGER = logging.getLogger(__name__)


class WorkerSupervisor:
    """Enforces a single controller; UI clients never receive process ownership."""

    def __init__(
        self,
        recording_factory: Callable[[], HeadlessRecordingController] | None = None,
        *,
        inhibitor: PowerInhibitorPort | None = None,
        power_status: PowerStatusPort | None = None,
        prevent_suspend: bool = False,
        block_lid_close: bool = False,
        hotplug_monitor: UdevVideoHotplugMonitor | None = None,
        camera_identity: str | None = None,
        video_identity_resolver: Callable[[str], object | None] = resolve_video_identity,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        storage_governor: StorageGovernorPort | None = None,
        estimated_segment_bytes: int = 0,
    ) -> None:
        self._recording_factory = recording_factory
        self._controller: HeadlessRecordingController | None = None
        self._session_id: str | None = None
        self._state = SessionState.IDLE
        self._responses: dict[str, tuple[Command, Response]] = {}
        self._inhibitor = inhibitor
        self._power_status = power_status
        self._prevent_suspend = prevent_suspend
        self._block_lid_close = block_lid_close
        self._hotplug_monitor = hotplug_monitor
        self._camera_identity = camera_identity
        self._video_identity_resolver = video_identity_resolver
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._watchdog = CaptureWatchdog()
        self._health = self._fresh_health(SessionState.RECORDING_AV)
        self._heartbeat_monotonic = monotonic()
        self._recovery_attempt = 0
        self._retry_at_monotonic: float | None = None
        self._recovery_reason: RecoveryReason | None = None
        self._gap_started_monotonic: float | None = None
        self._gap_started_at: datetime | None = None
        self._last_gap_seconds: float | None = None
        self._last_good_video_monotonic: float | None = None
        self._last_good_audio_monotonic: float | None = None
        self._gaps: list[RecoveryGap] = []
        self._recovery_store = RecoveryJournalStore()
        self._storage_governor = storage_governor
        self._estimated_segment_bytes = estimated_segment_bytes

    @property
    def state(self) -> SessionState:
        return self._state

    def handle(self, request: Request) -> Response:
        previous = self._responses.get(request.command_id)
        if previous is not None:
            command, response = previous
            if command is not request.command:
                return self._response(request, False, "command_id_conflict")
            return response
        response = self._dispatch(request)
        self._responses[request.command_id] = (request.command, response)
        LOGGER.info(
            "ipc command protocol_version=1 command=%s command_id=%s state=%s accepted=%s error=%s",
            request.command.value,
            request.command_id,
            response.state,
            response.accepted,
            response.error_code,
        )
        return response

    def poll(self) -> None:
        self._heartbeat_monotonic = self._monotonic()
        if self._controller is None:
            return
        if self._state is SessionState.RECOVERING:
            self._attempt_recovery_if_due()
            return
        if self._state not in {
            SessionState.RECORDING_AV,
            SessionState.RECORDING_AUDIO_ONLY,
            SessionState.RECORDING_VIDEO_ONLY,
        }:
            return
        power = self._current_power_status()
        if power.source is PowerSource.CRITICAL_BATTERY:
            self._finalize_active("critical_battery")
            return
        if self._storage_governor is not None:
            decision = self._storage_governor.ensure_working_reserve(
                self._estimated_segment_bytes, recording_active=True
            )
            if decision.safe_stop_required:
                self._finalize_active("critical_storage")
                return
        if (
            self._prevent_suspend
            and self._inhibitor is not None
            and not self._inhibitor.protection_active()
        ):
            self._finalize_active("power_inhibition_lost")
            return
        self._poll_hotplug()
        if self._state is SessionState.RECOVERING:
            return
        if getattr(self._controller, "is_running", True) is False:
            self._enter_recovery(RecoveryReason.FFMPEG_EXITED)
            return
        self._health = self._watchdog.observe(
            getattr(self._controller, "progress", None),
            getattr(self._controller, "active_output_bytes", lambda: None)(),
            self._heartbeat_monotonic,
        )
        reason = self._watchdog.recovery_reason(self._health)
        if reason is not None:
            self._enter_recovery(reason)
            return
        try:
            result = self._controller.poll()
        except RecordingFailure as error:
            self._enter_recovery(RecoveryReason.FFMPEG_EXITED, detail=str(error))
            return
        if result is not None:
            self._enter_recovery(RecoveryReason.FFMPEG_EXITED)

    def _dispatch(self, request: Request) -> Response:
        if request.command is Command.STATUS:
            return self._response(request, True)
        if request.command is Command.START:
            return self._start(request)
        if request.command is Command.STOP:
            return self._stop(request)
        if request.command is Command.RETRY:
            return self._retry(request)
        if request.command is Command.FORCE_STOP:
            return self._force_stop(request)
        raise AssertionError("all protocol commands are handled")

    def _start(self, request: Request) -> Response:
        if self._state in {
            SessionState.STARTING,
            SessionState.RECORDING_AV,
            SessionState.STOPPING,
            SessionState.FINALIZING,
        }:
            return self._response(request, True)
        if self._recording_factory is None:
            return self._response(request, False, "recording_configuration_unavailable")
        if self._current_power_status().source is PowerSource.CRITICAL_BATTERY:
            return self._response(request, False, "critical_battery")
        if self._storage_governor is not None:
            decision = self._storage_governor.ensure_working_reserve(
                self._estimated_segment_bytes, recording_active=False
            )
            if decision.remaining_bytes_needed:
                return self._response(request, False, "insufficient_storage_reserve")
        if self._prevent_suspend:
            if self._inhibitor is None:
                return self._response(request, False, "power_inhibition_unavailable")
            try:
                self._inhibitor.acquire(block_lid_close=self._block_lid_close)
            except InhibitionError as error:
                LOGGER.error("power inhibition acquisition failed: %s", error)
                return self._response(request, False, "power_inhibition_unavailable")
        self._controller = self._recording_factory()
        self._transition(SessionState.STARTING, "start requested")
        try:
            started: StartedRecording = self._controller.start()
        except RecordingFailure as error:
            self._release_inhibition()
            self._transition(SessionState.FAILED, str(error))
            return self._response(request, False, "recording_start_failed")
        self._session_id = str(started.session_id)
        self._watchdog = CaptureWatchdog()
        self._watchdog.arm(self._monotonic())
        self._health = self._fresh_health(SessionState.RECORDING_AV)
        self._transition(SessionState.RECORDING_AV, "FFmpeg started")
        if self._hotplug_monitor is not None:
            self._hotplug_monitor.start()
        return self._response(request, True)

    def _stop(self, request: Request) -> Response:
        if self._state in {SessionState.IDLE, SessionState.COMPLETED}:
            return self._response(request, True)
        if self._state in {SessionState.STOPPING, SessionState.FINALIZING}:
            return self._response(request, True)
        if self._controller is None:
            return self._response(request, False, "no_active_recording")
        return self._finalize_active("user_requested", request)

    def _retry(self, request: Request) -> Response:
        if self._state is SessionState.RECOVERING:
            self._retry_at_monotonic = self._monotonic()
            self._persist_recovery()
            self._attempt_recovery_if_due()
            return self._response(request, self._state is not SessionState.FAILED)
        if self._state is not SessionState.FAILED:
            return self._response(request, False, "retry_not_available")
        self._controller = None
        self._session_id = None
        self._transition(SessionState.IDLE, "retry requested")
        return self._start(request)

    def _force_stop(self, request: Request) -> Response:
        if self._controller is None or self._state not in {
            SessionState.STARTING,
            SessionState.RECORDING_AV,
            SessionState.STOPPING,
            SessionState.FINALIZING,
        }:
            return self._response(request, False, "no_active_recording")
        LOGGER.error("explicit last-resort force-stop command_id=%s", request.command_id)
        self._controller.force_stop()
        self._release_inhibition()
        self._close_hotplug_monitor()
        self._transition(SessionState.FAILED, "explicit force-stop requested")
        return self._response(request, True)

    def _response(
        self, request: Request, accepted: bool, error_code: str | None = None
    ) -> Response:
        power = self._current_power_status()
        protection = self._protection_state()
        return Response(
            request.command,
            request.command_id,
            self._state.value,
            accepted,
            error_code,
            self._session_id,
            protection.value,
            power.source.value,
            power.battery_percent,
            self._health.video.value,
            self._health.audio.value,
            self._health.output.value,
            max(0.0, self._monotonic() - self._heartbeat_monotonic),
            self._recovery_attempt,
            (
                max(0.0, self._retry_at_monotonic - self._monotonic())
                if self._retry_at_monotonic is not None
                else None
            ),
            self._last_gap_seconds,
            self._recovery_reason.value if self._recovery_reason is not None else None,
        )

    def finalize_for_shutdown(self, graceful_timeout_seconds: float = 10) -> int:
        """Finalizes active evidence before the unit's documented stop timeout expires."""
        if self._controller is None or self._state not in {
            SessionState.STARTING,
            SessionState.RECORDING_AV,
            SessionState.STOPPING,
            SessionState.FINALIZING,
        }:
            self._release_inhibition()
            return 0
        result = self._finalize_active(
            "shutdown_requested", graceful_timeout_seconds=graceful_timeout_seconds
        )
        return 0 if result.accepted else 1

    def _finalize_active(
        self,
        reason: str,
        request: Request | None = None,
        *,
        graceful_timeout_seconds: float = 10,
    ) -> Response:
        error_code: str | None
        if self._controller is None:
            if request is None:
                return Response(Command.STATUS, "shutdown", self._state.value, False)
            return self._response(request, False, "no_active_recording")
        self._transition(SessionState.STOPPING, f"{reason} safe stop requested")
        try:
            self._controller.append_event("finalization_requested", {"reason": reason})
            self._controller.stop(graceful_timeout_seconds, reason=reason)
        except RecordingFailure as error:
            self._transition(SessionState.FAILED, f"{reason}: {error}")
            accepted = False
            error_code = (
                "shutdown_finalization_failed"
                if reason == "shutdown_requested"
                else "safe_stop_failed"
            )
        else:
            self._transition(SessionState.FINALIZING, "FFmpeg finalized")
            self._transition(SessionState.COMPLETED, f"{reason} safe stop completed")
            accepted = True
            error_code = None
        finally:
            self._release_inhibition()
            self._close_hotplug_monitor()
        if request is None:
            return Response(Command.STATUS, "shutdown", self._state.value, accepted, error_code)
        return self._response(request, accepted, error_code)

    def _poll_hotplug(self) -> None:
        if self._hotplug_monitor is None:
            return
        for event in self._hotplug_monitor.poll():
            if (
                event.action == "add"
                and self._state is SessionState.RECORDING_AUDIO_ONLY
                and self._camera_identity is not None
                and self._video_identity_resolver(self._camera_identity) is not None
            ):
                self._enter_recovery(RecoveryReason.VIDEO_RESTORED)
                return
            if event.action == "remove" and (
                self._camera_identity is None
                or self._video_identity_resolver(self._camera_identity) is None
            ):
                self._health = CaptureHealth(
                    HealthState.DISCONNECTED,
                    self._health.audio,
                    self._health.output,
                    self._health.video_age_seconds,
                    self._health.audio_age_seconds,
                    self._health.output_age_seconds,
                )
                self._enter_recovery(RecoveryReason.VIDEO_DISCONNECTED)
                return

    def _enter_recovery(self, reason: RecoveryReason, *, detail: str | None = None) -> None:
        if self._controller is None or self._state is SessionState.RECOVERING:
            return
        try:
            begin_recovery = getattr(self._controller, "begin_recovery", None)
            if begin_recovery is None:
                self._controller.stop(reason=reason.value)
            else:
                begin_recovery(reason.value)
        except RecordingFailure as error:
            self._transition(SessionState.FAILED, f"recovery finalization failed: {error}")
            return
        self._transition(SessionState.RECOVERING, detail or reason.value)
        self._recovery_reason = reason
        self._recovery_attempt = 0
        self._gap_started_monotonic = self._monotonic()
        self._gap_started_at = self._wall_clock()
        self._last_good_video_monotonic = self._watchdog.last_good_video_monotonic
        self._last_good_audio_monotonic = self._watchdog.last_good_audio_monotonic
        self._retry_at_monotonic = self._gap_started_monotonic + RetrySchedule.delay_for_attempt(1)
        self._controller.append_event(
            "capture_gap_started",
            {
                "reason": reason.value,
                "started_at": self._gap_started_at.isoformat(),
                "started_monotonic": self._gap_started_monotonic,
                "last_good_video_monotonic": self._last_good_video_monotonic,
                "last_good_audio_monotonic": self._last_good_audio_monotonic,
            },
        )
        self._persist_recovery()

    def _attempt_recovery_if_due(self) -> None:
        if self._controller is None or self._retry_at_monotonic is None:
            return
        now = self._monotonic()
        if now < self._retry_at_monotonic:
            return
        self._recovery_attempt += 1
        target = self._recovery_target()
        try:
            if (
                target is not SessionState.RECORDING_AUDIO_ONLY
                and self._camera_identity is not None
            ):
                if self._video_identity_resolver(self._camera_identity) is None:
                    raise RecordingFailure("selected camera identity is unavailable")
            resume = getattr(self._controller, "resume_after_recovery", None)
            if resume is None:
                raise RecordingFailure("recovery controller is unavailable")
            resume(target)
        except (OSError, RecordingFailure) as error:
            delay = RetrySchedule.delay_for_attempt(self._recovery_attempt + 1)
            self._retry_at_monotonic = now + delay
            self._persist_recovery()
            LOGGER.warning("recovery attempt=%s failed: %s", self._recovery_attempt, error)
            return
        self._watchdog = CaptureWatchdog()
        self._watchdog.arm(now)
        self._health = self._fresh_health(target)
        self._state = target
        if self._gap_started_monotonic is not None:
            self._last_gap_seconds = now - self._gap_started_monotonic
        self._retry_at_monotonic = None
        self._controller.append_event(
            "capture_gap_ended",
            {
                "reason": self._recovery_reason.value if self._recovery_reason else "unknown",
                "duration_seconds": self._last_gap_seconds,
                "attempts": self._recovery_attempt,
                "ended_at": self._wall_clock().isoformat(),
            },
        )
        if self._gap_started_at is not None and self._gap_started_monotonic is not None:
            self._gaps.append(
                RecoveryGap(
                    self._recovery_reason.value if self._recovery_reason else "unknown",
                    self._gap_started_at.isoformat(),
                    self._wall_clock().isoformat(),
                    self._gap_started_monotonic,
                    self._last_gap_seconds,
                    self._recovery_attempt,
                    self._last_good_video_monotonic,
                    self._last_good_audio_monotonic,
                )
            )
        self._gap_started_at = None
        self._gap_started_monotonic = None
        self._persist_recovery()
        self._transition(target, "recovery started a new segment")

    def _recovery_target(self) -> SessionState:
        if self._recovery_reason in {
            RecoveryReason.VIDEO_STALLED,
            RecoveryReason.VIDEO_DISCONNECTED,
        }:
            if self._health.audio in {HealthState.HEALTHY, HealthState.WARNING}:
                return SessionState.RECORDING_AUDIO_ONLY
        if self._recovery_reason is RecoveryReason.AUDIO_STALLED:
            if self._health.video in {HealthState.HEALTHY, HealthState.WARNING}:
                return SessionState.RECORDING_VIDEO_ONLY
        return SessionState.RECORDING_AV

    def _persist_recovery(self) -> None:
        directory = getattr(self._controller, "session_directory", None)
        if directory is None:
            return
        gaps = tuple(self._gaps)
        if self._gap_started_at is not None and self._gap_started_monotonic is not None:
            gaps += (
                RecoveryGap(
                    self._recovery_reason.value if self._recovery_reason else "unknown",
                    self._gap_started_at.isoformat(),
                    self._wall_clock().isoformat() if self._last_gap_seconds is not None else None,
                    self._gap_started_monotonic,
                    self._last_gap_seconds,
                    self._recovery_attempt,
                    self._last_good_video_monotonic,
                    self._last_good_audio_monotonic,
                ),
            )
        self._recovery_store.save(
            directory / "recovery.json",
            RecoveryJournal(
                self._state.value,
                self._recovery_attempt,
                self._retry_at_monotonic,
                gaps,
            ),
        )

    @staticmethod
    def _fresh_health(target: SessionState) -> CaptureHealth:
        """Report no old-process capture health while a replacement warms up."""
        return CaptureHealth(
            (
                HealthState.DISCONNECTED
                if target is SessionState.RECORDING_AUDIO_ONLY
                else HealthState.UNKNOWN
            ),
            (
                HealthState.DISCONNECTED
                if target is SessionState.RECORDING_VIDEO_ONLY
                else HealthState.UNKNOWN
            ),
            HealthState.UNKNOWN,
            None,
            None,
            None,
        )

    def _release_inhibition(self) -> None:
        if self._inhibitor is not None:
            self._inhibitor.release()

    def _close_hotplug_monitor(self) -> None:
        close = getattr(self._hotplug_monitor, "close", None)
        if close is not None:
            close()

    def _current_power_status(self) -> PowerStatus:
        if self._power_status is None:
            return PowerStatus(PowerProtectionState.INACTIVE, PowerSource.UNKNOWN)
        return self._power_status.status()

    def _protection_state(self) -> PowerProtectionState:
        if not self._prevent_suspend:
            return PowerProtectionState.INACTIVE
        if self._inhibitor is None:
            return PowerProtectionState.UNAVAILABLE
        if self._inhibitor.protection_active():
            return PowerProtectionState.ACTIVE
        if self._state is SessionState.RECORDING_AV:
            return PowerProtectionState.LOST
        return PowerProtectionState.INACTIVE

    def _transition(self, target: SessionState, context: str) -> None:
        previous = self._state
        self._state = target
        LOGGER.info(
            "worker state changed previous=%s current=%s context=%s",
            previous.value,
            target.value,
            context,
        )
