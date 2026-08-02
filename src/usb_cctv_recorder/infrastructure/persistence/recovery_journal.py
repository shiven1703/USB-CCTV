"""Atomically published recovery facts; media remains owned by the recorder."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from usb_cctv_recorder.infrastructure.storage.atomic_files import AtomicPublisher


@dataclass(frozen=True, slots=True)
class RecoveryGap:
    reason: str
    started_at: str
    ended_at: str | None
    started_monotonic: float
    duration_seconds: float | None
    attempts: int
    last_good_video_monotonic: float | None
    last_good_audio_monotonic: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "started_monotonic": self.started_monotonic,
            "duration_seconds": self.duration_seconds,
            "attempts": self.attempts,
            "last_good_video_monotonic": self.last_good_video_monotonic,
            "last_good_audio_monotonic": self.last_good_audio_monotonic,
        }


@dataclass(frozen=True, slots=True)
class RecoveryJournal:
    state: str
    attempt: int
    retry_at_monotonic: float | None
    gaps: tuple[RecoveryGap, ...] = ()
    schema_version: int = 1

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "state": self.state,
                    "attempt": self.attempt,
                    "retry_at_monotonic": self.retry_at_monotonic,
                    "gaps": [gap.to_dict() for gap in self.gaps],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


class RecoveryJournalStore:
    def __init__(self, publisher: AtomicPublisher | None = None) -> None:
        self._publisher = publisher or AtomicPublisher()

    def save(self, path: Path, journal: RecoveryJournal) -> None:
        self._publisher.publish_bytes(path, journal.to_json().encode("utf-8"), replace=True)
