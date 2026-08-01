"""Phase 4 failure paths retain completed evidence and record explicit causes."""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    build_synthetic_recording_command,
)
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import FfprobeVerifier, MediaVerificationError
from usb_cctv_recorder.infrastructure.persistence.event_journal import JsonlEventJournal
from usb_cctv_recorder.worker.recording import HeadlessRecordingController, RecordingFailure


class FailsAfterOneSegment(FfprobeVerifier):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def verify(self, path: Path, **kwargs: object):  # type: ignore[override]
        self.calls += 1
        if self.calls > 1:
            raise MediaVerificationError("injected verifier failure")
        return super().verify(path, **kwargs)


def test_nonzero_ffmpeg_exit_marks_manifest_failed(tmp_path: Path) -> None:
    controller = HeadlessRecordingController(
        tmp_path,
        lambda _: (sys.executable, "-c", "raise SystemExit(7)"),
    )
    started = controller.start()
    with pytest.raises(RecordingFailure, match="return code 7"):
        controller.run_until_complete()
    assert controller.manifest.state.value == "failed"
    assert "return code 7" in (controller.manifest.failure_reason or "")
    assert (
        JsonlEventJournal(started.directory / "events.jsonl").read_all()[-1].event_type
        == "session_failed"
    )


def test_later_verifier_failure_preserves_earlier_finalized_segment(tmp_path: Path) -> None:
    controller = HeadlessRecordingController(
        tmp_path,
        lambda pattern: build_synthetic_recording_command(
            pattern, 1, duration_seconds=2.4, realtime=True
        ),
        verifier=FailsAfterOneSegment(),
    )
    started = controller.start()
    for _ in range(20):
        time.sleep(0.2)
        controller.poll()
        if controller.manifest.segments:
            break
    assert controller.manifest.segments
    first = started.directory / controller.manifest.segments[0].filename
    before = hashlib.sha256(first.read_bytes()).hexdigest()
    with pytest.raises(RecordingFailure, match="injected"):
        controller.run_until_complete()
    assert hashlib.sha256(first.read_bytes()).hexdigest() == before
    assert controller.manifest.state.value == "failed"
    assert first.name in {segment.filename for segment in controller.manifest.segments}


def test_unwritable_later_output_keeps_an_earlier_finalized_segment(tmp_path: Path) -> None:
    controller = HeadlessRecordingController(
        tmp_path,
        lambda pattern: build_synthetic_recording_command(
            pattern, 1, duration_seconds=4.2, realtime=True
        ),
    )
    started = controller.start()
    for _ in range(20):
        time.sleep(0.2)
        controller.poll()
        if controller.manifest.segments:
            break
    assert controller.manifest.segments
    first = started.directory / controller.manifest.segments[0].filename
    before = hashlib.sha256(first.read_bytes()).hexdigest()
    os.chmod(started.directory, 0o500)
    try:
        with pytest.raises(RecordingFailure, match="persist session manifest"):
            controller.run_until_complete()
    finally:
        os.chmod(started.directory, 0o700)
    assert hashlib.sha256(first.read_bytes()).hexdigest() == before
