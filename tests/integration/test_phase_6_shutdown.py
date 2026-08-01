"""Phase 6 shutdown finalization retains finalized media and durable context."""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

from usb_cctv_recorder.application.dto import PowerProtectionState, PowerSource, PowerStatus
from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    build_synthetic_recording_command,
)
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request
from usb_cctv_recorder.infrastructure.persistence.event_journal import JsonlEventJournal
from usb_cctv_recorder.worker.recording import HeadlessRecordingController
from usb_cctv_recorder.worker.supervisor import WorkerSupervisor


class _Inhibitor:
    def __init__(self) -> None:
        self.active = False
        self.released = False

    def acquire(self, *, block_lid_close: bool) -> None:
        assert not block_lid_close
        self.active = True

    def release(self) -> None:
        self.active = False
        self.released = True

    def protection_active(self) -> bool:
        return self.active


class _Power:
    def status(self) -> PowerStatus:
        return PowerStatus(PowerProtectionState.INACTIVE, PowerSource.AC)


def _request(command: Command) -> Request:
    return Request(command, str(uuid.uuid4()))


def test_shutdown_finalization_keeps_finalized_media_unchanged_and_persists_reason(
    tmp_path: Path,
) -> None:
    created: list[HeadlessRecordingController] = []

    def factory() -> HeadlessRecordingController:
        controller = HeadlessRecordingController(
            tmp_path,
            lambda pattern: build_synthetic_recording_command(pattern, 1, realtime=True),
        )
        created.append(controller)
        return controller

    inhibitor = _Inhibitor()
    supervisor = WorkerSupervisor(
        factory,
        inhibitor=inhibitor,
        power_status=_Power(),
        prevent_suspend=True,
    )
    assert supervisor.handle(_request(Command.START)).accepted
    controller = created[0]
    deadline = time.monotonic() + 4
    while not controller.manifest.segments:
        supervisor.poll()
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert controller.manifest.segments
    first = controller.session_directory / controller.manifest.segments[0].filename
    before = hashlib.sha256(first.read_bytes()).hexdigest()

    assert supervisor.finalize_for_shutdown(3) == 0
    assert hashlib.sha256(first.read_bytes()).hexdigest() == before
    assert controller.manifest.stop_reason == "shutdown_requested"
    events = JsonlEventJournal(controller.session_directory / "events.jsonl").read_all()
    event_types = [event.event_type for event in events]
    assert event_types.index("finalization_requested") < event_types.index("stop_requested")
    assert event_types.index("stop_requested") < event_types.index("session_stopped")
    assert inhibitor.released
