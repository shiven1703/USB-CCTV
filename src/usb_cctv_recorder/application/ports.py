"""Application boundary contracts. Infrastructure implements these protocols."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Protocol

from usb_cctv_recorder.application.configuration import WorkerRecordingConfiguration
from usb_cctv_recorder.application.dto import (
    AudioSource,
    LibraryDetails,
    LibraryFilter,
    LibraryItem,
    PowerStatus,
    VideoDevice,
)
from usb_cctv_recorder.domain.entities import ArchiveJob, ComponentHealth, RecordingSession, Segment
from usb_cctv_recorder.domain.value_objects import MonotonicDuration, SessionId, UtcTimestamp


class VideoDevicePort(Protocol):
    def list_video_devices(self) -> Sequence[VideoDevice]: ...


class AudioDevicePort(Protocol):
    def list_audio_devices(self) -> Sequence[AudioSource]: ...


class MediaProcessPort(Protocol):
    def start(self, arguments: Sequence[str]) -> None: ...

    def request_graceful_stop(self) -> None: ...

    def is_running(self) -> bool: ...


class PowerInhibitorPort(Protocol):
    def acquire(self, *, block_lid_close: bool) -> None: ...

    def release(self) -> None: ...

    def protection_active(self) -> bool: ...


class PowerStatusPort(Protocol):
    def status(self) -> PowerStatus: ...


class PersistencePort(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...

    def save_session(self, session: RecordingSession) -> None: ...

    def save_segment(self, segment: Segment) -> None: ...

    def save_archive_job(self, job: ArchiveJob) -> None: ...


class ClockPort(Protocol):
    def now(self) -> UtcTimestamp: ...

    def monotonic(self) -> float: ...


class FilesystemPort(Protocol):
    def open_read(self, path: Path) -> BinaryIO: ...

    def publish_bytes(self, destination: Path, content: bytes) -> None: ...


class SystemServicePort(Protocol):
    def start_worker(self) -> None: ...

    def stop_worker(self) -> None: ...


class WorkerConfigurationPort(Protocol):
    def save(self, configuration: WorkerRecordingConfiguration) -> None: ...


class LibraryCataloguePort(Protocol):
    """Browse and mutate catalogue facts without exposing SQLite to the UI."""

    def rebuild(self, media_root: Path) -> int: ...

    def count(self, filters: LibraryFilter) -> int: ...

    def page(self, filters: LibraryFilter, offset: int, limit: int) -> tuple[LibraryItem, ...]: ...

    def details(self, item_id: str) -> LibraryDetails: ...

    def set_protected(self, item_id: str, protected: bool) -> LibraryItem: ...

    def reverify(self, item_id: str) -> LibraryItem: ...


class EventJournalPort(Protocol):
    def append(
        self, event_type: str, occurred_at: UtcTimestamp, payload: dict[str, object]
    ) -> None: ...


class HealthPort(Protocol):
    def health(self) -> Iterator[ComponentHealth]: ...


class WallAndMonotonicClock:
    """Small standard-library implementation usable by later composition roots."""

    def now(self) -> UtcTimestamp:
        return UtcTimestamp(datetime.now().astimezone())

    def duration_since(
        self, started_monotonic: float, current_monotonic: float
    ) -> MonotonicDuration:
        return MonotonicDuration(current_monotonic - started_monotonic)


def session_identifier(session: RecordingSession) -> SessionId:
    """Keep a typed helper at the application boundary for adapter contracts."""
    return session.id
