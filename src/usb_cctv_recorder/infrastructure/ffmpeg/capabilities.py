"""FFmpeg capability enumeration; candidates still need Phase 4 smoke tests."""

from __future__ import annotations

import re

from usb_cctv_recorder.application.dto import FfmpegCapabilities
from usb_cctv_recorder.infrastructure.commands.runner import StructuredCommandRunner

_ENCODER = re.compile(r"^\s*V\S*\s+(?P<name>\S+)")
_MUXER = re.compile(r"^\s*[D. ]?[E]\s+(?P<names>\S+)")


def parse_encoder_candidates(output: str) -> tuple[str, ...]:
    """Report H.264/HEVC encoders without asserting runtime usability."""
    candidates: list[str] = []
    for line in output.splitlines():
        match = _ENCODER.match(line)
        if match is not None and any(
            token in match.group("name") for token in ("264", "265", "hevc")
        ):
            candidates.append(match.group("name"))
    return tuple(candidates)


def parse_muxers(output: str) -> tuple[str, ...]:
    muxers: list[str] = []
    for line in output.splitlines():
        match = _MUXER.match(line)
        if match is not None:
            muxers.extend(match.group("names").split(","))
    return tuple(muxers)


class FfmpegCapabilityProbe:
    def __init__(self, runner: StructuredCommandRunner) -> None:
        self._runner = runner

    def probe(self) -> FfmpegCapabilities:
        encoders = self._runner.run(("ffmpeg", "-hide_banner", "-encoders"))
        muxers = self._runner.run(("ffmpeg", "-hide_banner", "-muxers"))
        return FfmpegCapabilities(
            parse_encoder_candidates(encoders.stdout) if encoders.succeeded else (),
            parse_muxers(muxers.stdout) if muxers.succeeded else (),
        )
