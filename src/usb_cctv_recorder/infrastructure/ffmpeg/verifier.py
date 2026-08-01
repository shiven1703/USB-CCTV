"""FFprobe validation before a finalized recording becomes authoritative."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from usb_cctv_recorder.infrastructure.commands.runner import StructuredCommandRunner


class MediaVerificationError(RuntimeError):
    """FFprobe could not establish that a completed segment is usable."""


@dataclass(frozen=True, slots=True)
class VerifiedMedia:
    path: Path
    duration_seconds: float
    video_codec: str | None
    audio_codec: str | None


class FfprobeVerifier:
    def __init__(self, runner: StructuredCommandRunner | None = None) -> None:
        self._runner = runner or StructuredCommandRunner(timeout_seconds=15)

    def verify(
        self,
        path: Path,
        *,
        expect_video: bool = True,
        expect_audio: bool = True,
        minimum_duration_seconds: float = 0.05,
    ) -> VerifiedMedia:
        if minimum_duration_seconds <= 0:
            raise ValueError("minimum duration must be positive")
        if not path.is_file():
            raise MediaVerificationError(f"segment does not exist: {path}")
        result = self._runner.run(
            (
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            )
        )
        if not result.succeeded:
            raise MediaVerificationError(
                result.stderr or result.execution_error or "ffprobe failed"
            )
        try:
            document = json.loads(result.stdout)
            streams = document["streams"]
            format_duration = float(document["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise MediaVerificationError("ffprobe returned incomplete metadata") from error
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        if expect_video and video is None:
            raise MediaVerificationError("expected video stream is missing")
        if expect_audio and audio is None:
            raise MediaVerificationError("expected audio stream is missing")
        if format_duration < minimum_duration_seconds:
            raise MediaVerificationError("segment duration is implausibly short")
        return VerifiedMedia(
            path=path,
            duration_seconds=format_duration,
            video_codec=str(video["codec_name"]) if video is not None else None,
            audio_codec=str(audio["codec_name"]) if audio is not None else None,
        )
