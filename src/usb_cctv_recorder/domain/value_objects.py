"""Immutable, validated values shared by the domain and its adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from .errors import DomainError


@dataclass(frozen=True, slots=True)
class SessionId:
    value: UUID

    @classmethod
    def new(cls) -> SessionId:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> SessionId:
        try:
            return cls(UUID(value))
        except ValueError as error:
            raise DomainError(f"invalid session id: {value!r}") from error

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class SegmentId:
    value: UUID

    @classmethod
    def new(cls) -> SegmentId:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> SegmentId:
        try:
            return cls(UUID(value))
        except ValueError as error:
            raise DomainError(f"invalid segment id: {value!r}") from error

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ArchiveJobId:
    value: UUID

    @classmethod
    def new(cls) -> ArchiveJobId:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> ArchiveJobId:
        try:
            return cls(UUID(value))
        except ValueError as error:
            raise DomainError(f"invalid archive job id: {value!r}") from error

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class UtcTimestamp:
    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise DomainError("timestamps must be timezone-aware")

    @classmethod
    def parse(cls, value: str) -> UtcTimestamp:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise DomainError(f"invalid timestamp: {value!r}") from error
        return cls(parsed)

    def as_utc(self) -> datetime:
        return self.value.astimezone(UTC)

    def isoformat(self) -> str:
        return self.as_utc().isoformat()


@dataclass(frozen=True, slots=True)
class MonotonicDuration:
    seconds: float

    def __post_init__(self) -> None:
        if self.seconds < 0:
            raise DomainError("monotonic duration cannot be negative")


@dataclass(frozen=True, slots=True)
class MediaProfile:
    width: int
    height: int
    frame_rate: float
    video_codec: str
    audio_codec: str

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.frame_rate <= 0:
            raise DomainError("media dimensions and frame rate must be positive")
        if not self.video_codec or not self.audio_codec:
            raise DomainError("media codecs are required")
