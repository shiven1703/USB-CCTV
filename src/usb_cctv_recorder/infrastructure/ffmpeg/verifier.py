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
    video_streams: int = 0
    audio_streams: int = 0
    width: int | None = None
    height: int | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None


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
            video_streams=sum(stream.get("codec_type") == "video" for stream in streams),
            audio_streams=sum(stream.get("codec_type") == "audio" for stream in streams),
            width=_optional_int(video.get("width")) if video is not None else None,
            height=_optional_int(video.get("height")) if video is not None else None,
            audio_sample_rate=_optional_int(audio.get("sample_rate"))
            if audio is not None
            else None,
            audio_channels=_optional_int(audio.get("channels")) if audio is not None else None,
        )

    def verify_full_decode(self, path: Path) -> None:
        """Decode every mapped stream; probe metadata alone is not enough evidence."""
        if not path.is_file():
            raise MediaVerificationError(f"segment does not exist: {path}")
        result = self._runner.run(
            (
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(path),
                "-map",
                "0",
                "-f",
                "null",
                "-",
            )
        )
        if not result.succeeded:
            raise MediaVerificationError(
                result.stderr or result.execution_error or "full decode failed"
            )

    def audio_packet_hashes(self, path: Path) -> tuple[str, ...]:
        """Return ordered encoded-audio packet hashes for a stream-copy archive comparison."""
        result = self._runner.run(
            (
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_packets",
                "-show_data_hash",
                "sha256",
                "-show_entries",
                "packet=data_hash",
                "-of",
                "json",
                str(path),
            )
        )
        if not result.succeeded:
            raise MediaVerificationError(
                result.stderr or result.execution_error or "audio packet inspection failed"
            )
        try:
            packets = json.loads(result.stdout).get("packets", [])
            hashes = tuple(str(packet["data_hash"]) for packet in packets)
        except (AttributeError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise MediaVerificationError(
                "ffprobe returned incomplete audio packet hashes"
            ) from error
        if not hashes:
            raise MediaVerificationError("audio stream has no encoded packets")
        return hashes


def _optional_int(value: object) -> int | None:
    if not isinstance(value, int | str | bytes | bytearray):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
