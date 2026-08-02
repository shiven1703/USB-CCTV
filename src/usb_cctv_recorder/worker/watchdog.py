"""Monotonic capture watchdogs and bounded retry scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from usb_cctv_recorder.domain.states import HealthState
from usb_cctv_recorder.infrastructure.ffmpeg.progress_parser import ProgressSnapshot


class RecoveryReason(StrEnum):
    VIDEO_STALLED = "video_stalled"
    AUDIO_STALLED = "audio_stalled"
    OUTPUT_STALLED = "output_stalled"
    FFMPEG_EXITED = "ffmpeg_exited"
    VIDEO_DISCONNECTED = "video_disconnected"
    VIDEO_RESTORED = "video_restored"


@dataclass(frozen=True, slots=True)
class CaptureHealth:
    video: HealthState
    audio: HealthState
    output: HealthState
    video_age_seconds: float | None
    audio_age_seconds: float | None
    output_age_seconds: float | None


class _ProgressSignal:
    def __init__(self) -> None:
        self.value: int | float | None = None
        self.updated_at: float | None = None

    def observe(self, value: int | float | None, now: float) -> None:
        if value is not None and value != self.value:
            self.value = value
            self.updated_at = now

    def arm(self, now: float) -> None:
        """Start a new process watchdog window before its first progress record arrives."""
        self.value = None
        self.updated_at = now

    def state_at(self, now: float) -> tuple[HealthState, float | None]:
        if self.updated_at is None:
            return HealthState.UNKNOWN, None
        age = max(0.0, now - self.updated_at)
        if age >= 15:
            return HealthState.STALLED, age
        if age >= 5:
            return HealthState.WARNING, age
        return HealthState.HEALTHY, age

    @property
    def last_updated(self) -> float | None:
        return self.updated_at


class CaptureWatchdog:
    """Tracks independent video frame, encoded-audio time, and output-byte progress."""

    def __init__(self) -> None:
        self._video = _ProgressSignal()
        self._audio = _ProgressSignal()
        self._output = _ProgressSignal()

    def observe(
        self, progress: ProgressSnapshot | None, output_bytes: int | None, now_monotonic: float
    ) -> CaptureHealth:
        if now_monotonic < 0:
            raise ValueError("monotonic time must be non-negative")
        if progress is not None:
            self._video.observe(progress.frame, now_monotonic)
            # FFmpeg progress exposes encoded output timestamps. With an audio mapping this is
            # the available packet-progress signal; stream verification still decides authority.
            self._audio.observe(progress.output_seconds, now_monotonic)
            self._output.observe(progress.output_bytes, now_monotonic)
        self._output.observe(output_bytes, now_monotonic)
        video, video_age = self._video.state_at(now_monotonic)
        audio, audio_age = self._audio.state_at(now_monotonic)
        output, output_age = self._output.state_at(now_monotonic)
        return CaptureHealth(video, audio, output, video_age, audio_age, output_age)

    def arm(self, now_monotonic: float) -> None:
        """Discard old-process evidence and apply thresholds to the new process from now."""
        if now_monotonic < 0:
            raise ValueError("monotonic time must be non-negative")
        self._video.arm(now_monotonic)
        self._audio.arm(now_monotonic)
        self._output.arm(now_monotonic)

    @property
    def last_good_video_monotonic(self) -> float | None:
        return self._video.last_updated

    @property
    def last_good_audio_monotonic(self) -> float | None:
        return self._audio.last_updated

    @staticmethod
    def recovery_reason(health: CaptureHealth) -> RecoveryReason | None:
        if health.video is HealthState.STALLED:
            return RecoveryReason.VIDEO_STALLED
        if health.audio is HealthState.STALLED:
            return RecoveryReason.AUDIO_STALLED
        if health.output is HealthState.STALLED:
            return RecoveryReason.OUTPUT_STALLED
        return None


class RetrySchedule:
    """The fixed Phase 7 retry policy; it deliberately has no unbounded backoff growth."""

    delays_seconds = (2, 5, 10, 30, 60)

    @classmethod
    def delay_for_attempt(cls, attempt: int) -> int:
        if attempt <= 0:
            raise ValueError("attempt must be positive")
        return cls.delays_seconds[min(attempt - 1, len(cls.delays_seconds) - 1)]
