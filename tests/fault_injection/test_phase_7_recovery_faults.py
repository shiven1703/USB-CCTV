"""Phase 7 interruption preservation and explicit degraded-media fault checks."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import pytest

from usb_cctv_recorder.domain.states import SessionState
from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    build_synthetic_recording_command,
)
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import FfprobeVerifier, MediaVerificationError
from usb_cctv_recorder.infrastructure.persistence.event_journal import JsonlEventJournal
from usb_cctv_recorder.worker.recording import HeadlessRecordingController, RecordingFailure


def _synthetic(pattern: Path) -> tuple[str, ...]:
    return build_synthetic_recording_command(pattern, 60, duration_seconds=30, realtime=True)


def test_recovery_preserves_completed_media_and_always_uses_a_new_segment(tmp_path: Path) -> None:
    controller = HeadlessRecordingController(tmp_path, _synthetic)
    started = controller.start()
    time.sleep(0.8)
    assert controller.begin_recovery("ffmpeg_exited")
    assert controller.manifest.segments
    completed = started.directory / controller.manifest.segments[0].filename
    before = hashlib.sha256(completed.read_bytes()).hexdigest()

    controller.resume_after_recovery(SessionState.RECORDING_AV)
    time.sleep(0.8)
    controller.stop()

    assert hashlib.sha256(completed.read_bytes()).hexdigest() == before
    assert list(started.directory.glob("recovery-001-*.mkv"))
    event_types = [
        event.event_type
        for event in JsonlEventJournal(started.directory / "events.jsonl").read_all()
    ]
    assert "segment_interrupted_verified" in event_types


class _RejectInterruptedVerification(FfprobeVerifier):
    def verify(self, path: Path, **_kwargs: object):  # type: ignore[override]
        raise MediaVerificationError(f"injected interruption failure for {path.name}")


def test_unverified_interrupted_media_is_quarantined_without_deletion(tmp_path: Path) -> None:
    controller = HeadlessRecordingController(
        tmp_path, _synthetic, verifier=_RejectInterruptedVerification()
    )
    started = controller.start()
    time.sleep(0.8)
    assert controller.begin_recovery("video_disconnected")

    quarantined = list((tmp_path / "quarantine" / str(started.session_id)).glob("*.mkv"))
    assert quarantined and quarantined[0].is_file()
    assert not list(started.directory.glob("segment-*.mkv"))


def test_recovery_guardrails_do_not_create_an_emergency_file_without_an_explicit_mode(
    tmp_path: Path,
) -> None:
    controller = HeadlessRecordingController(tmp_path, _synthetic)
    with pytest.raises(RecordingFailure, match="not started"):
        controller.begin_recovery("video_stalled")
    controller.start()
    time.sleep(0.4)
    assert controller.begin_recovery("video_stalled")
    assert not controller.begin_recovery("video_stalled")
    with pytest.raises(RecordingFailure, match="recovery start failed"):
        controller.resume_after_recovery(SessionState.RECORDING_AUDIO_ONLY)


def test_failed_quarantine_leaves_the_interrupted_file_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = HeadlessRecordingController(tmp_path, _synthetic)
    controller.start()
    candidate = controller.session_directory / "segment-bad.mkv"
    candidate.write_bytes(b"interrupted")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("full")

    monkeypatch.setattr(os, "replace", fail_replace)
    controller._quarantine_interrupted(candidate, "injected")
    assert candidate.exists()
    monkeypatch.undo()
    candidate.unlink()
    controller.stop()


def test_audio_only_and_video_only_synthetic_segments_validate_their_actual_streams(
    tmp_path: Path,
) -> None:
    verifier = FfprobeVerifier()
    for name, video, audio in (("audio", False, True), ("video", True, False)):
        pattern = tmp_path / f"{name}-%06d.mkv"
        result = subprocess.run(
            build_synthetic_recording_command(
                pattern,
                60,
                duration_seconds=0.6,
                include_video=video,
                include_audio=audio,
            ),
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode()
        media = verifier.verify(
            tmp_path / f"{name}-000000.mkv", expect_video=video, expect_audio=audio
        )
        assert (media.video_codec is not None) is video
        assert (media.audio_codec is not None) is audio
