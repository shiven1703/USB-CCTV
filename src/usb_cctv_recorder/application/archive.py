"""Application-facing archive queue use cases."""

from __future__ import annotations

from pathlib import Path

from .dto import ArchiveJobView, ArchiveRequest, LibraryItem
from .ports import ArchivePort


class ArchiveService:
    """Presentation-facing facade; all evidence I/O stays behind ``ArchivePort``."""

    def __init__(self, archive: ArchivePort) -> None:
        self._archive = archive

    def enqueue(self, request: ArchiveRequest) -> tuple[ArchiveJobView, ...]:
        return self._archive.enqueue(request)

    def jobs(self) -> tuple[ArchiveJobView, ...]:
        return self._archive.jobs()

    def run_next(self) -> ArchiveJobView | None:
        return self._archive.run_next()

    def pause(self, job_id: str) -> ArchiveJobView:
        return self._archive.pause(job_id)

    def resume(self, job_id: str) -> ArchiveJobView:
        return self._archive.resume(job_id)

    def cancel(self, job_id: str) -> ArchiveJobView:
        return self._archive.cancel(job_id)

    def retry(self, job_id: str) -> ArchiveJobView:
        return self._archive.retry(job_id)

    def recover_partials(self) -> tuple[ArchiveJobView, ...]:
        return self._archive.recover_partials()

    def select_session(self, session_id: str) -> tuple[str, ...]:
        return self._archive.select_session(session_id)

    def select_oldest_for_space(self, requested_bytes: int) -> tuple[str, ...]:
        return self._archive.select_oldest_for_space(requested_bytes)

    def move_to_active_library(self, item_id: str, active_root: Path) -> LibraryItem:
        return self._archive.move_to_active_library(item_id, active_root)

    def create_share_copy(self, item_id: str, destination: Path) -> LibraryItem:
        return self._archive.create_share_copy(item_id, destination)
