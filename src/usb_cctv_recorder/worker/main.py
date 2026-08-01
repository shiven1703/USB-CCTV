"""Headless development worker entrypoint; systemd ownership is Phase 5 work."""

from __future__ import annotations

from pathlib import Path

from usb_cctv_recorder.application.dto import CaptureMode
from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    CameraCapture,
    FfmpegRecordingCommandBuilder,
    OutputProfile,
    RecordingSettings,
    build_synthetic_recording_command,
)

from .recording import HeadlessRecordingController, RecordingFailure


def run_worker(
    *,
    media_root: Path | None = None,
    camera_identity: str | None = None,
    microphone_source: str | None = None,
    width: int = 2560,
    height: int = 1440,
    input_frame_rate: float = 30,
    output_frame_rate: float = 15,
    segment_minutes: int = 60,
    synthetic_duration_seconds: float | None = None,
) -> int:
    """Run one foreground recording; Ctrl-C requests FFmpeg's graceful finalization."""
    if media_root is None:
        return 0
    if synthetic_duration_seconds is not None:

        def command_factory(output_pattern: Path) -> tuple[str, ...]:
            return build_synthetic_recording_command(
                output_pattern, segment_minutes * 60, duration_seconds=synthetic_duration_seconds
            )
    else:
        if camera_identity is None or microphone_source is None:
            raise ValueError("camera identity and microphone source are required for recording")
        persistent = Path(camera_identity)
        resolved = persistent.resolve(strict=True)

        def command_factory(output_pattern: Path) -> tuple[str, ...]:
            return FfmpegRecordingCommandBuilder().build(
                RecordingSettings(
                    camera=CameraCapture(
                        camera_identity,
                        resolved,
                        CaptureMode("MJPG", "Motion-JPEG", width, height, input_frame_rate),
                    ),
                    microphone_source=microphone_source,
                    output_profile=OutputProfile(width, height, output_frame_rate),
                    segment_seconds=segment_minutes * 60,
                    output_pattern=output_pattern,
                )
            )

    controller = HeadlessRecordingController(media_root, command_factory)
    try:
        controller.start()
        controller.run_until_complete()
    except KeyboardInterrupt:
        controller.stop()
    except RecordingFailure:
        return 1
    return 0
