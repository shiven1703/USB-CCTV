"""Synthetic FFmpeg coverage for safe segmented recording without camera hardware."""

from __future__ import annotations

import time
from pathlib import Path

from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    build_synthetic_recording_command,
)
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import FfprobeVerifier
from usb_cctv_recorder.infrastructure.persistence.event_journal import JsonlEventJournal
from usb_cctv_recorder.worker.recording import HeadlessRecordingController


def test_three_synthetic_segments_are_verified_and_persisted(tmp_path: Path) -> None:
    controller = HeadlessRecordingController(
        tmp_path,
        lambda pattern: build_synthetic_recording_command(pattern, 1, duration_seconds=3.2),
    )
    started = controller.start()
    result = controller.run_until_complete()

    assert result.returncode == 0
    files = sorted(started.directory.glob("segment-*.mkv"))
    assert len(files) >= 3
    verifier = FfprobeVerifier()
    for path in files:
        media = verifier.verify(path)
        assert media.video_codec == "h264"
        assert media.audio_codec == "aac"
        assert media.duration_seconds >= 0.05
    assert controller.manifest.state.value == "completed"
    assert {segment.filename for segment in controller.manifest.segments} == {
        path.name for path in files
    }
    events = JsonlEventJournal(started.directory / "events.jsonl").read_all()
    assert [event.event_type for event in events].count("segment_finalized") == len(files)


def test_safe_stop_finalizes_a_short_active_synthetic_segment(tmp_path: Path) -> None:
    controller = HeadlessRecordingController(
        tmp_path,
        lambda pattern: build_synthetic_recording_command(pattern, 1, realtime=True),
    )
    started = controller.start()
    time.sleep(0.6)
    result = controller.stop(graceful_timeout_seconds=3)

    files = sorted(started.directory.glob("segment-*.mkv"))
    assert result.graceful_stop_requested
    assert files
    assert len(controller.manifest.segments) == len(files)
    assert FfprobeVerifier().verify(files[-1]).duration_seconds < 1
    assert controller.manifest.stop_reason == "user_requested"
