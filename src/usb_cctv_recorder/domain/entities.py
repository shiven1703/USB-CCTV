"""Authoritative recorder entities with explicit immutable lifecycle changes."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .states import (
    ARCHIVE_JOB_TRANSITIONS,
    HEALTH_TRANSITIONS,
    SEGMENT_TRANSITIONS,
    SESSION_TRANSITIONS,
    ArchiveJobState,
    HealthState,
    SegmentState,
    SessionState,
    transition,
)
from .value_objects import ArchiveJobId, MonotonicDuration, SegmentId, SessionId, UtcTimestamp


@dataclass(frozen=True, slots=True)
class RecordingSession:
    id: SessionId
    state: SessionState
    created_at: UtcTimestamp

    def move_to(self, target: SessionState) -> RecordingSession:
        return replace(self, state=transition(self.state, target, SESSION_TRANSITIONS))


@dataclass(frozen=True, slots=True)
class Segment:
    id: SegmentId
    session_id: SessionId
    state: SegmentState
    started_at: UtcTimestamp
    duration: MonotonicDuration | None = None

    def move_to(self, target: SegmentState) -> Segment:
        return replace(self, state=transition(self.state, target, SEGMENT_TRANSITIONS))


@dataclass(frozen=True, slots=True)
class ArchiveJob:
    id: ArchiveJobId
    segment_id: SegmentId
    state: ArchiveJobState
    created_at: UtcTimestamp

    def move_to(self, target: ArchiveJobState) -> ArchiveJob:
        return replace(self, state=transition(self.state, target, ARCHIVE_JOB_TRANSITIONS))


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    component: str
    state: HealthState
    observed_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not self.component:
            raise ValueError("health component is required")

    def move_to(self, target: HealthState, observed_at: UtcTimestamp) -> ComponentHealth:
        return replace(
            self,
            state=transition(self.state, target, HEALTH_TRANSITIONS),
            observed_at=observed_at,
        )
