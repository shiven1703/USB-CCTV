"""Phase 2 domain value objects and state-machine contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from usb_cctv_recorder.application.configuration import RecorderConfiguration
from usb_cctv_recorder.application.ports import WallAndMonotonicClock, session_identifier
from usb_cctv_recorder.domain.entities import ArchiveJob, ComponentHealth, RecordingSession, Segment
from usb_cctv_recorder.domain.errors import DomainError, InvalidStateTransition
from usb_cctv_recorder.domain.states import (
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
from usb_cctv_recorder.domain.value_objects import (
    ArchiveJobId,
    MediaProfile,
    MonotonicDuration,
    SegmentId,
    SessionId,
    UtcTimestamp,
)

NOW = UtcTimestamp(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))


@pytest.mark.parametrize(
    ("states", "allowed"),
    [
        (SessionState, SESSION_TRANSITIONS),
        (SegmentState, SEGMENT_TRANSITIONS),
        (ArchiveJobState, ARCHIVE_JOB_TRANSITIONS),
        (HealthState, HEALTH_TRANSITIONS),
    ],
)
def test_each_state_machine_declares_every_state_and_accepts_each_valid_transition(
    states: type[SessionState] | type[SegmentState] | type[ArchiveJobState] | type[HealthState],
    allowed: object,
) -> None:
    transition_map = allowed
    assert set(transition_map) == set(states)  # type: ignore[arg-type]
    for current, targets in transition_map.items():  # type: ignore[union-attr]
        for target in targets:
            assert transition(current, target, transition_map) is target  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("states", "allowed"),
    [
        (SessionState, SESSION_TRANSITIONS),
        (SegmentState, SEGMENT_TRANSITIONS),
        (ArchiveJobState, ARCHIVE_JOB_TRANSITIONS),
        (HealthState, HEALTH_TRANSITIONS),
    ],
)
def test_each_state_machine_rejects_every_undeclared_transition(
    states: type[SessionState] | type[SegmentState] | type[ArchiveJobState] | type[HealthState],
    allowed: object,
) -> None:
    transition_map = allowed
    for current in states:
        for target in states:
            if target not in transition_map[current]:  # type: ignore[index]
                with pytest.raises(InvalidStateTransition):
                    transition(current, target, transition_map)  # type: ignore[arg-type]


def test_entities_return_immutable_updated_state() -> None:
    session = RecordingSession(SessionId.new(), SessionState.IDLE, NOW)
    segment = Segment(SegmentId.new(), session.id, SegmentState.OPEN, NOW)
    job = ArchiveJob(ArchiveJobId.new(), segment.id, ArchiveJobState.QUEUED, NOW)
    health = ComponentHealth("video", HealthState.UNKNOWN, NOW)

    assert session_identifier(session.move_to(SessionState.PREFLIGHT)) == session.id
    assert segment.move_to(SegmentState.FINALIZING).state is SegmentState.FINALIZING
    assert job.move_to(ArchiveJobState.PRECHECK).state is ArchiveJobState.PRECHECK
    assert health.move_to(HealthState.HEALTHY, NOW).state is HealthState.HEALTHY
    assert session.state is SessionState.IDLE


def test_value_objects_validate_identifiers_timestamps_durations_and_media() -> None:
    identifier = "123e4567-e89b-12d3-a456-426614174000"
    assert str(SessionId.parse(identifier)) == identifier
    assert str(SegmentId.parse(identifier)) == identifier
    assert str(ArchiveJobId.parse(identifier)) == identifier
    assert UtcTimestamp(datetime(2026, 8, 1, 14, 0, tzinfo=UTC)).isoformat().endswith("+00:00")
    assert MonotonicDuration(1.5).seconds == 1.5
    assert MediaProfile(2560, 1440, 15, "libx264", "aac").width == 2560

    with pytest.raises(DomainError):
        SessionId.parse("not-a-uuid")
    with pytest.raises(DomainError):
        UtcTimestamp(datetime(2026, 8, 1, 12, 0))
    with pytest.raises(DomainError):
        MonotonicDuration(-1)
    with pytest.raises(DomainError):
        MediaProfile(0, 1440, 15, "libx264", "aac")
    with pytest.raises(DomainError):
        MediaProfile(10, 10, 1, "", "aac")


def test_monotonic_duration_is_not_affected_by_wall_clock_jump() -> None:
    clock = WallAndMonotonicClock()
    assert clock.duration_since(100.0, 115.25) == MonotonicDuration(15.25)
    assert NOW.value + timedelta(hours=1) != NOW.value


def test_configuration_enforces_phase_two_storage_limits(tmp_path: pytest.TempPathFactory) -> None:
    media_root = tmp_path / "media"
    configuration = RecorderConfiguration(media_root=media_root)
    assert configuration.segment_duration_minutes == 60

    with pytest.raises(ValueError, match="absolute"):
        RecorderConfiguration(media_root=media_root.relative_to(tmp_path))
    with pytest.raises(ValueError, match="between 1 and 360"):
        RecorderConfiguration(media_root=media_root, segment_duration_minutes=0)
    with pytest.raises(ValueError, match="90,000,000,000"):
        RecorderConfiguration(media_root=media_root, configured_storage_cap_bytes=90_000_000_001)
    with pytest.raises(ValueError, match="operating-system"):
        RecorderConfiguration(media_root=media_root, operating_system_reserve_bytes=-1)
    with pytest.raises(ValueError, match="emergency"):
        RecorderConfiguration(media_root=media_root, emergency_finalization_reserve_bytes=-1)


def test_component_health_requires_a_named_component() -> None:
    with pytest.raises(ValueError, match="component"):
        ComponentHealth("", HealthState.UNKNOWN, NOW)
