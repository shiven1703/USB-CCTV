"""Explicit lifecycle state machines for authoritative recorder records."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar

from .errors import InvalidStateTransition


class SessionState(StrEnum):
    IDLE = "idle"
    PREFLIGHT = "preflight"
    STARTING = "starting"
    RECORDING_AV = "recording_av"
    RECORDING_AUDIO_ONLY = "recording_audio_only"
    RECORDING_VIDEO_ONLY = "recording_video_only"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    STOPPING = "stopping"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class SegmentState(StrEnum):
    OPEN = "open"
    FINALIZING = "finalizing"
    VERIFIED = "verified"
    INTERRUPTED_VERIFIED = "interrupted_verified"
    INTERRUPTED_UNVERIFIED = "interrupted_unverified"
    QUARANTINED = "quarantined"
    ARCHIVE_QUEUED = "archive_queued"
    ARCHIVING = "archiving"
    ARCHIVE_VALIDATING = "archive_validating"
    ARCHIVED_VERIFIED = "archived_verified"
    PROTECTED = "protected"
    DELETED = "deleted"


class ArchiveJobState(StrEnum):
    QUEUED = "queued"
    PRECHECK = "precheck"
    TRANSCODING = "transcoding"
    FLUSHING = "flushing"
    VALIDATING = "validating"
    PUBLISHING = "publishing"
    COMMITTED = "committed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"


class HealthState(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    WARNING = "warning"
    STALLED = "stalled"
    DISCONNECTED = "disconnected"
    RECOVERING = "recovering"
    FAILED = "failed"


_LifecycleState = TypeVar(
    "_LifecycleState", SessionState, SegmentState, ArchiveJobState, HealthState
)


def _transitions(
    state_type: type[_LifecycleState], **entries: set[_LifecycleState]
) -> dict[_LifecycleState, frozenset[_LifecycleState]]:
    return {state_type[name]: frozenset(targets) for name, targets in entries.items()}


SESSION_TRANSITIONS: Mapping[SessionState, frozenset[SessionState]] = _transitions(
    SessionState,
    IDLE={SessionState.PREFLIGHT},
    PREFLIGHT={SessionState.IDLE, SessionState.STARTING, SessionState.FAILED},
    STARTING={
        SessionState.RECORDING_AV,
        SessionState.RECORDING_AUDIO_ONLY,
        SessionState.RECORDING_VIDEO_ONLY,
        SessionState.DEGRADED,
        SessionState.RECOVERING,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    RECORDING_AV={
        SessionState.DEGRADED,
        SessionState.RECOVERING,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    RECORDING_AUDIO_ONLY={
        SessionState.RECORDING_AV,
        SessionState.DEGRADED,
        SessionState.RECOVERING,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    RECORDING_VIDEO_ONLY={
        SessionState.RECORDING_AV,
        SessionState.DEGRADED,
        SessionState.RECOVERING,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    DEGRADED={
        SessionState.RECORDING_AV,
        SessionState.RECORDING_AUDIO_ONLY,
        SessionState.RECORDING_VIDEO_ONLY,
        SessionState.RECOVERING,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    RECOVERING={
        SessionState.RECORDING_AV,
        SessionState.RECORDING_AUDIO_ONLY,
        SessionState.RECORDING_VIDEO_ONLY,
        SessionState.DEGRADED,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    STOPPING={SessionState.FINALIZING, SessionState.FAILED},
    FINALIZING={SessionState.COMPLETED, SessionState.FAILED},
    COMPLETED=set(),
    FAILED=set(),
)

SEGMENT_TRANSITIONS: Mapping[SegmentState, frozenset[SegmentState]] = _transitions(
    SegmentState,
    OPEN={
        SegmentState.FINALIZING,
        SegmentState.INTERRUPTED_VERIFIED,
        SegmentState.INTERRUPTED_UNVERIFIED,
    },
    FINALIZING={
        SegmentState.VERIFIED,
        SegmentState.INTERRUPTED_VERIFIED,
        SegmentState.INTERRUPTED_UNVERIFIED,
    },
    VERIFIED={SegmentState.ARCHIVE_QUEUED, SegmentState.PROTECTED, SegmentState.DELETED},
    INTERRUPTED_VERIFIED={
        SegmentState.ARCHIVE_QUEUED,
        SegmentState.PROTECTED,
        SegmentState.DELETED,
    },
    INTERRUPTED_UNVERIFIED={SegmentState.QUARANTINED},
    QUARANTINED={SegmentState.PROTECTED, SegmentState.DELETED},
    ARCHIVE_QUEUED={SegmentState.ARCHIVING, SegmentState.VERIFIED, SegmentState.PROTECTED},
    ARCHIVING={SegmentState.ARCHIVE_VALIDATING, SegmentState.VERIFIED},
    ARCHIVE_VALIDATING={SegmentState.ARCHIVED_VERIFIED, SegmentState.VERIFIED},
    ARCHIVED_VERIFIED={SegmentState.PROTECTED, SegmentState.DELETED},
    PROTECTED={
        SegmentState.VERIFIED,
        SegmentState.INTERRUPTED_VERIFIED,
        SegmentState.ARCHIVED_VERIFIED,
        SegmentState.QUARANTINED,
    },
    DELETED=set(),
)

ARCHIVE_JOB_TRANSITIONS: Mapping[ArchiveJobState, frozenset[ArchiveJobState]] = _transitions(
    ArchiveJobState,
    QUEUED={ArchiveJobState.PRECHECK, ArchiveJobState.PAUSED, ArchiveJobState.CANCELLED},
    PRECHECK={
        ArchiveJobState.TRANSCODING,
        ArchiveJobState.PAUSED,
        ArchiveJobState.CANCELLED,
        ArchiveJobState.FAILED,
    },
    TRANSCODING={
        ArchiveJobState.FLUSHING,
        ArchiveJobState.PAUSED,
        ArchiveJobState.CANCELLED,
        ArchiveJobState.FAILED,
    },
    FLUSHING={
        ArchiveJobState.VALIDATING,
        ArchiveJobState.PAUSED,
        ArchiveJobState.CANCELLED,
        ArchiveJobState.FAILED,
    },
    VALIDATING={
        ArchiveJobState.PUBLISHING,
        ArchiveJobState.PAUSED,
        ArchiveJobState.CANCELLED,
        ArchiveJobState.FAILED,
    },
    PUBLISHING={ArchiveJobState.COMMITTED, ArchiveJobState.FAILED},
    COMMITTED=set(),
    PAUSED={ArchiveJobState.QUEUED, ArchiveJobState.CANCELLED},
    CANCELLED=set(),
    FAILED=set(),
)

HEALTH_TRANSITIONS: Mapping[HealthState, frozenset[HealthState]] = _transitions(
    HealthState,
    UNKNOWN={
        HealthState.HEALTHY,
        HealthState.WARNING,
        HealthState.STALLED,
        HealthState.DISCONNECTED,
        HealthState.RECOVERING,
        HealthState.FAILED,
    },
    HEALTHY={
        HealthState.WARNING,
        HealthState.STALLED,
        HealthState.DISCONNECTED,
        HealthState.FAILED,
    },
    WARNING={
        HealthState.HEALTHY,
        HealthState.STALLED,
        HealthState.DISCONNECTED,
        HealthState.RECOVERING,
        HealthState.FAILED,
    },
    STALLED={
        HealthState.HEALTHY,
        HealthState.DISCONNECTED,
        HealthState.RECOVERING,
        HealthState.FAILED,
    },
    DISCONNECTED={HealthState.RECOVERING, HealthState.FAILED},
    RECOVERING={
        HealthState.HEALTHY,
        HealthState.WARNING,
        HealthState.STALLED,
        HealthState.DISCONNECTED,
        HealthState.FAILED,
    },
    FAILED={HealthState.RECOVERING},
)


def transition(
    current: _LifecycleState,
    target: _LifecycleState,
    allowed: Mapping[_LifecycleState, frozenset[_LifecycleState]],
) -> _LifecycleState:
    """Validate and return one explicit lifecycle transition."""
    if target not in allowed[current]:
        raise InvalidStateTransition(f"cannot transition {current.value!r} to {target.value!r}")
    return target
