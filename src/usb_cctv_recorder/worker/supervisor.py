"""Worker-owned recording control exposed through the closed IPC protocol."""

from __future__ import annotations

import logging
from collections.abc import Callable

from usb_cctv_recorder.domain.states import SessionState
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request, Response

from .recording import HeadlessRecordingController, RecordingFailure, StartedRecording

LOGGER = logging.getLogger(__name__)


class WorkerSupervisor:
    """Enforces a single controller; UI clients never receive process ownership."""

    def __init__(
        self, recording_factory: Callable[[], HeadlessRecordingController] | None = None
    ) -> None:
        self._recording_factory = recording_factory
        self._controller: HeadlessRecordingController | None = None
        self._session_id: str | None = None
        self._state = SessionState.IDLE
        self._responses: dict[str, tuple[Command, Response]] = {}

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
        if self._controller is None or self._state is not SessionState.RECORDING_AV:
            return
        try:
            result = self._controller.poll()
        except RecordingFailure as error:
            self._transition(SessionState.FAILED, str(error))
            return
        if result is not None:
            self._transition(SessionState.COMPLETED, "recording process exited")

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
        self._controller = self._recording_factory()
        self._transition(SessionState.STARTING, "start requested")
        try:
            started: StartedRecording = self._controller.start()
        except RecordingFailure as error:
            self._transition(SessionState.FAILED, str(error))
            return self._response(request, False, "recording_start_failed")
        self._session_id = str(started.session_id)
        self._transition(SessionState.RECORDING_AV, "FFmpeg started")
        return self._response(request, True)

    def _stop(self, request: Request) -> Response:
        if self._state in {SessionState.IDLE, SessionState.COMPLETED}:
            return self._response(request, True)
        if self._state in {SessionState.STOPPING, SessionState.FINALIZING}:
            return self._response(request, True)
        if self._controller is None:
            return self._response(request, False, "no_active_recording")
        self._transition(SessionState.STOPPING, "safe stop requested")
        try:
            self._controller.stop()
        except RecordingFailure as error:
            self._transition(SessionState.FAILED, str(error))
            return self._response(request, False, "safe_stop_failed")
        self._transition(SessionState.FINALIZING, "FFmpeg finalized")
        self._transition(SessionState.COMPLETED, "safe stop completed")
        return self._response(request, True)

    def _retry(self, request: Request) -> Response:
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
        self._transition(SessionState.FAILED, "explicit force-stop requested")
        return self._response(request, True)

    def _response(
        self, request: Request, accepted: bool, error_code: str | None = None
    ) -> Response:
        return Response(
            request.command,
            request.command_id,
            self._state.value,
            accepted,
            error_code,
            self._session_id,
        )

    def _transition(self, target: SessionState, context: str) -> None:
        previous = self._state
        self._state = target
        LOGGER.info(
            "worker state changed previous=%s current=%s context=%s",
            previous.value,
            target.value,
            context,
        )
