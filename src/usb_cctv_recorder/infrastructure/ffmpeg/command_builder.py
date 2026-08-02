"""Validated argv construction for the Phase 4 FFmpeg recording pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from usb_cctv_recorder.application.dto import CaptureMode


@dataclass(frozen=True, slots=True)
class OutputProfile:
    """The encoded output profile, deliberately separate from the camera input mode."""

    width: int
    height: int
    frames_per_second: float
    video_codec: str = "libx264"
    video_bitrate_kbit: int = 3500
    audio_codec: str = "aac"
    audio_bitrate_kbit: int = 128
    audio_sample_rate: int = 48000
    audio_channels: int = 1

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.frames_per_second <= 0:
            raise ValueError("output dimensions and frame rate must be positive")
        if self.video_codec != "libx264":
            raise ValueError("Phase 4 uses the runtime-proven libx264 fallback only")
        if self.video_bitrate_kbit <= 0 or self.audio_bitrate_kbit <= 0:
            raise ValueError("output bitrates must be positive")
        if self.audio_codec != "aac":
            raise ValueError("Phase 4 supports AAC audio only")
        if self.audio_sample_rate != 48000 or self.audio_channels != 1:
            raise ValueError("Phase 4 requires mono 48 kHz audio")


@dataclass(frozen=True, slots=True)
class CameraCapture:
    """A selected persistent V4L2 identity and its freshly resolved capture node."""

    persistent_identity: str
    resolved_path: Path
    capture_mode: CaptureMode

    def __post_init__(self) -> None:
        if not self.persistent_identity.startswith("/dev/v4l/by-id/"):
            raise ValueError("camera identity must be a persistent /dev/v4l/by-id path")
        if not self.resolved_path.is_absolute() or not self.resolved_path.name.startswith("video"):
            raise ValueError("resolved camera path must be an absolute V4L2 video node")
        if self.capture_mode.pixel_format != "MJPG":
            raise ValueError("Phase 4 camera input must use the selected MJPEG mode")


@dataclass(frozen=True, slots=True)
class RecordingSettings:
    """Fully validated settings used to produce one segmented MKV command."""

    camera: CameraCapture
    microphone_source: str
    output_profile: OutputProfile
    segment_seconds: int
    output_pattern: Path

    def __post_init__(self) -> None:
        if not self.microphone_source or self.microphone_source in {"default", "@DEFAULT_SOURCE@"}:
            raise ValueError("an explicit Pulse microphone source is required")
        if not 1 <= self.segment_seconds <= 21_600:
            raise ValueError("segment duration must be between 1 second and 360 minutes")
        if not self.output_pattern.is_absolute() or self.output_pattern.suffix != ".mkv":
            raise ValueError("segment output pattern must be an absolute MKV path")
        if "%06d" not in self.output_pattern.name:
            raise ValueError("segment output pattern must contain the fixed %06d sequence")


class FfmpegRecordingCommandBuilder:
    """Builds only argument vectors; it never delegates parsing to a shell."""

    def build(self, settings: RecordingSettings) -> tuple[str, ...]:
        return self.build_for_streams(settings, include_video=True, include_audio=True)

    def build_for_streams(
        self, settings: RecordingSettings, *, include_video: bool, include_audio: bool
    ) -> tuple[str, ...]:
        """Build an AV or explicit emergency single-stream command without filler streams."""
        if not include_video and not include_audio:
            raise ValueError("at least one capture stream is required")
        mode = settings.camera.capture_mode
        profile = settings.output_profile
        # The segment muxer only cuts cleanly at keyframes. Force one at each boundary.
        keyframe_expression = f"expr:gte(t,n_forced*{settings.segment_seconds})"
        command: list[str] = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "warning",
            "-progress",
            "pipe:1",
            "-stats_period",
            "1",
        ]
        if include_video:
            command.extend(
                (
                    "-f",
                    "v4l2",
                    "-input_format",
                    "mjpeg",
                    "-video_size",
                    f"{mode.width}x{mode.height}",
                    "-framerate",
                    f"{mode.frames_per_second:g}",
                    "-i",
                    str(settings.camera.resolved_path),
                )
            )
        if include_audio:
            command.extend(
                (
                    "-f",
                    "pulse",
                    "-ar",
                    str(profile.audio_sample_rate),
                    "-ac",
                    str(profile.audio_channels),
                    "-i",
                    settings.microphone_source,
                )
            )
        if include_video:
            command.extend(("-map", "0:v:0", "-r", f"{profile.frames_per_second:g}"))
            command.extend(
                (
                    "-c:v",
                    profile.video_codec,
                    "-b:v",
                    f"{profile.video_bitrate_kbit}k",
                    "-force_key_frames",
                    keyframe_expression,
                )
            )
        if include_audio:
            audio_input = 1 if include_video else 0
            command.extend(("-map", f"{audio_input}:a:0"))
            command.extend(
                (
                    "-c:a",
                    profile.audio_codec,
                    "-b:a",
                    f"{profile.audio_bitrate_kbit}k",
                    "-ar",
                    str(profile.audio_sample_rate),
                    "-ac",
                    str(profile.audio_channels),
                )
            )
        command.extend(
            (
                "-f",
                "segment",
                "-segment_format",
                "matroska",
                "-segment_time",
                str(settings.segment_seconds),
                "-reset_timestamps",
                "1",
                "-n",
                str(settings.output_pattern),
            )
        )
        return tuple(command)


def build_synthetic_recording_command(
    output_pattern: Path,
    segment_seconds: int,
    *,
    duration_seconds: float | None = None,
    realtime: bool = False,
    include_video: bool = True,
    include_audio: bool = True,
) -> tuple[str, ...]:
    """Create the CI-only lavfi equivalent using the same output segmentation policy."""
    if not output_pattern.is_absolute() or "%06d" not in output_pattern.name:
        raise ValueError("synthetic output pattern must be an absolute fixed sequence pattern")
    if segment_seconds <= 0:
        raise ValueError("segment duration must be positive")
    if not include_video and not include_audio:
        raise ValueError("at least one capture stream is required")
    command: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-stats_period",
        "0.2",
    ]
    if realtime:
        command.append("-re")
    if include_video:
        command.extend(("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10"))
    if include_audio:
        command.extend(("-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000"))
    if duration_seconds is not None:
        if duration_seconds <= 0:
            raise ValueError("synthetic duration must be positive")
        command.extend(("-t", f"{duration_seconds:g}"))
    if include_video:
        command.extend(
            (
                "-map",
                "0:v:0",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-g",
                str(segment_seconds * 10),
                "-force_key_frames",
                f"expr:gte(t,n_forced*{segment_seconds})",
            )
        )
    if include_audio:
        command.extend(
            (
                "-map",
                f"{1 if include_video else 0}:a:0",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-ac",
                "1",
            )
        )
    command.extend(
        (
            "-f",
            "segment",
            "-segment_format",
            "matroska",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            "-n",
            str(output_pattern),
        )
    )
    return tuple(command)
