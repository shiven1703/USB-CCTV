"""Parser for FFmpeg's documented ``-progress`` key/value stream."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProgressHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    WARNING = "warning"
    STALLED = "stalled"
    FINISHED = "finished"


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    frame: int | None
    output_bytes: int | None
    output_seconds: float | None
    speed: float | None
    health: ProgressHealth
    is_final: bool


class FfmpegProgressParser:
    """Retains the latest complete progress block and calculates staleness monotonically."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._latest: ProgressSnapshot | None = None
        self._last_progress_monotonic: float | None = None

    @property
    def latest(self) -> ProgressSnapshot | None:
        return self._latest

    def feed_line(self, line: str, observed_monotonic: float) -> ProgressSnapshot | None:
        key, separator, value = line.strip().partition("=")
        if not separator or not key:
            return None
        self._values[key] = value
        if key != "progress" or value not in {"continue", "end"}:
            return None
        snapshot = ProgressSnapshot(
            frame=_as_int(self._values.get("frame")),
            output_bytes=_as_int(self._values.get("total_size")),
            output_seconds=_duration_seconds(self._values),
            speed=_speed(self._values.get("speed")),
            health=ProgressHealth.FINISHED if value == "end" else ProgressHealth.HEALTHY,
            is_final=value == "end",
        )
        self._latest = snapshot
        self._last_progress_monotonic = observed_monotonic
        self._values.clear()
        return snapshot

    def health_at(
        self,
        current_monotonic: float,
        *,
        warning_after_seconds: float = 5,
        stalled_after_seconds: float = 15,
    ) -> ProgressHealth:
        if warning_after_seconds <= 0 or stalled_after_seconds < warning_after_seconds:
            raise ValueError("progress health thresholds must be positive and ordered")
        if self._latest is not None and self._latest.is_final:
            return ProgressHealth.FINISHED
        if self._last_progress_monotonic is None:
            return ProgressHealth.UNKNOWN
        age = current_monotonic - self._last_progress_monotonic
        if age >= stalled_after_seconds:
            return ProgressHealth.STALLED
        if age >= warning_after_seconds:
            return ProgressHealth.WARNING
        return ProgressHealth.HEALTHY


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _duration_seconds(values: dict[str, str]) -> float | None:
    microseconds = _as_int(values.get("out_time_us") or values.get("out_time_ms"))
    if microseconds is not None:
        return microseconds / 1_000_000
    timestamp = values.get("out_time")
    if timestamp is None:
        return None
    try:
        hours, minutes, seconds = timestamp.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None


def _speed(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.removesuffix("x"))
    except ValueError:
        return None
