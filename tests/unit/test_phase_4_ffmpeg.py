"""Phase 4 command, progress, process, verifier, and lifecycle coverage."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from usb_cctv_recorder.application.dto import CaptureMode
from usb_cctv_recorder.infrastructure.commands.runner import CommandResult
from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    CameraCapture,
    FfmpegRecordingCommandBuilder,
    OutputProfile,
    RecordingSettings,
    build_synthetic_recording_command,
)
from usb_cctv_recorder.infrastructure.ffmpeg.process import FfmpegProcess, ProcessLifecycleError
from usb_cctv_recorder.infrastructure.ffmpeg.progress_parser import (
    FfmpegProgressParser,
    ProgressHealth,
)
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import FfprobeVerifier, MediaVerificationError


def _settings(tmp_path: Path) -> RecordingSettings:
    return RecordingSettings(
        CameraCapture(
            "/dev/v4l/by-id/usb-camera-video-index0",
            Path("/dev/video2"),
            CaptureMode("MJPG", "Motion-JPEG", 2560, 1440, 30),
        ),
        "alsa_input.usb-camera.mono-fallback",
        OutputProfile(2560, 1440, 15),
        60,
        tmp_path / "segment-%06d.mkv",
    )


def test_recording_command_uses_explicit_validated_capture_and_segment_settings(
    tmp_path: Path,
) -> None:
    command = FfmpegRecordingCommandBuilder().build(_settings(tmp_path))

    assert command[:7] == (
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
    )
    assert ("-input_format", "mjpeg") == (
        command[command.index("-input_format")],
        command[command.index("-input_format") + 1],
    )
    assert "/dev/video2" in command
    assert "alsa_input.usb-camera.mono-fallback" in command
    assert ("-segment_format", "matroska") == (
        command[command.index("-segment_format")],
        command[command.index("-segment_format") + 1],
    )
    assert "-force_key_frames" in command
    assert str(tmp_path / "segment-%06d.mkv") == command[-1]


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda tmp_path: CameraCapture(
                "/dev/video2", Path("/dev/video2"), CaptureMode("MJPG", "x", 1, 1, 1)
            ),
            "persistent",
        ),
        (
            lambda tmp_path: CameraCapture(
                "/dev/v4l/by-id/camera", Path("video2"), CaptureMode("MJPG", "x", 1, 1, 1)
            ),
            "absolute",
        ),
        (
            lambda tmp_path: CameraCapture(
                "/dev/v4l/by-id/camera", Path("/dev/video2"), CaptureMode("YUYV", "x", 1, 1, 1)
            ),
            "MJPEG",
        ),
    ],
)
def test_camera_capture_rejects_unstable_or_wrong_input(
    tmp_path: Path, factory: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory(tmp_path)  # type: ignore[operator]


def test_output_and_recording_settings_reject_unsafe_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        OutputProfile(0, 1, 1)
    with pytest.raises(ValueError, match="runtime-proven"):
        OutputProfile(1, 1, 1, video_codec="libx265")
    with pytest.raises(ValueError, match="bitrates"):
        OutputProfile(1, 1, 1, video_bitrate_kbit=0)
    with pytest.raises(ValueError, match="AAC"):
        OutputProfile(1, 1, 1, audio_codec="opus")
    with pytest.raises(ValueError, match="mono"):
        OutputProfile(1, 1, 1, audio_channels=2)
    with pytest.raises(ValueError, match="explicit Pulse"):
        RecordingSettings(
            _settings(tmp_path).camera,
            "default",
            OutputProfile(1, 1, 1),
            1,
            tmp_path / "segment-%06d.mkv",
        )
    with pytest.raises(ValueError, match="fixed"):
        RecordingSettings(
            _settings(tmp_path).camera, "mic", OutputProfile(1, 1, 1), 1, tmp_path / "segment.mkv"
        )
    with pytest.raises(ValueError, match="positive"):
        build_synthetic_recording_command(tmp_path / "segment-%06d.mkv", 0)
    with pytest.raises(ValueError, match="absolute"):
        build_synthetic_recording_command(Path("segment-%06d.mkv"), 1)
    with pytest.raises(ValueError, match="positive"):
        build_synthetic_recording_command(tmp_path / "segment-%06d.mkv", 1, duration_seconds=0)


def test_progress_parser_handles_normal_malformed_stalled_and_final_updates() -> None:
    parser = FfmpegProgressParser()
    assert parser.health_at(1) is ProgressHealth.UNKNOWN
    assert parser.feed_line("broken", 1) is None
    assert parser.feed_line("frame=12", 1) is None
    assert parser.feed_line("total_size=200", 1) is None
    assert parser.feed_line("out_time_us=1500000", 1) is None
    update = parser.feed_line("progress=continue", 1)
    assert update is not None
    assert update.frame == 12
    assert update.output_bytes == 200
    assert update.output_seconds == 1.5
    assert update.health is ProgressHealth.HEALTHY
    assert parser.health_at(7) is ProgressHealth.WARNING
    assert parser.health_at(16) is ProgressHealth.STALLED
    assert parser.feed_line("out_time=00:00:02.000000", 17) is None
    final = parser.feed_line("progress=end", 17)
    assert final is not None and final.is_final
    assert parser.health_at(100) is ProgressHealth.FINISHED
    with pytest.raises(ValueError, match="ordered"):
        parser.health_at(1, warning_after_seconds=2, stalled_after_seconds=1)
    parser.feed_line("speed=not-a-speed", 101)
    parser.feed_line("out_time=not-a-time", 101)
    malformed = parser.feed_line("progress=continue", 101)
    assert malformed is not None and malformed.speed is None and malformed.output_seconds is None


def test_process_wrapper_stops_gracefully_and_never_accepts_shell_strings() -> None:
    process = FfmpegProcess()
    script = "import signal,time; signal.signal(signal.SIGINT, lambda *_: exit(0)); time.sleep(60)"
    process.start((sys.executable, "-c", script))
    time.sleep(1)
    result = process.stop(graceful_timeout_seconds=2, terminate_timeout_seconds=1)
    assert result.returncode == 0
    assert result.graceful_stop_requested
    assert not result.forced_kill
    with pytest.raises(ProcessLifecycleError, match="already"):
        process.start((sys.executable, "-c", script))


def test_process_wrapper_reports_timeout_and_escalates_to_forced_kill() -> None:
    process = FfmpegProcess()
    script = (
        "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    )
    process.start((sys.executable, "-c", script))
    time.sleep(1)
    assert process.wait(0.01).timed_out
    result = process.stop(graceful_timeout_seconds=0.05, terminate_timeout_seconds=0.05)
    assert result.forced_kill
    assert result.returncode is not None
    with pytest.raises(ValueError, match="positive"):
        process.stop(0)


def test_ffprobe_verifier_rejects_missing_streams_and_implausible_duration(tmp_path: Path) -> None:
    verifier = FfprobeVerifier()
    with pytest.raises(MediaVerificationError, match="does not exist"):
        verifier.verify(tmp_path / "missing.mkv")
    with pytest.raises(ValueError, match="positive"):
        verifier.verify(tmp_path / "missing.mkv", minimum_duration_seconds=0)


class _Runner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result

    def run(self, arguments: tuple[str, ...]) -> CommandResult:
        assert arguments[0] == "ffprobe"
        return self.result


def test_ffprobe_verifier_handles_probe_errors_and_expected_stream_contracts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "segment.mkv"
    path.write_bytes(b"placeholder")
    failed = CommandResult(("ffprobe",), 1, "", "broken")
    with pytest.raises(MediaVerificationError, match="broken"):
        FfprobeVerifier(_Runner(failed)).verify(path)
    invalid = CommandResult(("ffprobe",), 0, "{}", "")
    with pytest.raises(MediaVerificationError, match="incomplete"):
        FfprobeVerifier(_Runner(invalid)).verify(path)
    video_only = CommandResult(
        ("ffprobe",),
        0,
        '{"format":{"duration":"0.01"},"streams":[{"codec_type":"video","codec_name":"h264"}]}',
        "",
    )
    with pytest.raises(MediaVerificationError, match="audio"):
        FfprobeVerifier(_Runner(video_only)).verify(path)
    with pytest.raises(MediaVerificationError, match="implausibly"):
        FfprobeVerifier(_Runner(video_only)).verify(path, expect_audio=False)
    valid = CommandResult(
        ("ffprobe",),
        0,
        '{"format":{"duration":"1.25"},"streams":[{"codec_type":"video","codec_name":"h264"},{"codec_type":"audio","codec_name":"aac"}]}',
        "",
    )
    verified = FfprobeVerifier(_Runner(valid)).verify(path)
    assert (verified.duration_seconds, verified.video_codec, verified.audio_codec) == (
        1.25,
        "h264",
        "aac",
    )
    audio_only = CommandResult(
        ("ffprobe",),
        0,
        '{"format":{"duration":"1"},"streams":[{"codec_type":"audio","codec_name":"aac"}]}',
        "",
    )
    with pytest.raises(MediaVerificationError, match="video"):
        FfprobeVerifier(_Runner(audio_only)).verify(path)


def test_process_wrapper_validates_start_and_collects_bounded_output() -> None:
    with pytest.raises(ValueError, match="positive"):
        FfmpegProcess(0)
    process = FfmpegProcess(maximum_output_bytes=5)
    assert not process.is_running()
    assert process.progress is None
    with pytest.raises(ValueError, match="non-empty"):
        process.start(())
    with pytest.raises(ProcessLifecycleError, match="unable"):
        process.start(("not-a-real-executable",))
    process.start(
        (sys.executable, "-c", "print('abcdefgh'); print('error', file=__import__('sys').stderr)")
    )
    result = process.wait(2)
    assert result.returncode == 0
    assert result.stdout.endswith("fgh\n")
    assert result.stderr.endswith("rror\n")
