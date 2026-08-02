"""Phase 9 evidence-safe archive transactions and durable queue recovery."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock
from uuid import uuid4

from usb_cctv_recorder.application.dto import (
    ArchiveJobStateView,
    ArchiveJobView,
    ArchiveProfileKind,
    ArchiveRequest,
    LibraryItem,
)
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import (
    FfprobeVerifier,
    MediaVerificationError,
    VerifiedMedia,
)
from usb_cctv_recorder.infrastructure.persistence.library_catalogue import (
    SQLiteLibraryCatalogue,
)

from .atomic_files import (
    AtomicPublisher,
    AtomicPublishError,
    CrossFilesystemCopier,
    _fsync_directory,
)
from .checksums import Sha256Service


class ArchiveTransactionError(RuntimeError):
    """The archive did not complete; the source is deliberately retained."""


class ArchiveCancelled(ArchiveTransactionError):
    """Cancellation is a normal terminal state and never publishes a partial."""


class FfmpegArchiveTranscoder:
    """Runs one validated ffmpeg argv and cooperatively stops it on cancellation."""

    def transcode(
        self, source: Path, partial: Path, bitrate_kbit: int, cancelled: Callable[[], bool]
    ) -> None:
        command = (
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-map_metadata",
            "0",
            "-c:v",
            "libx264",
            "-b:v",
            f"{bitrate_kbit}k",
            "-c:a",
            "copy",
            "-f",
            "matroska",
            "-n",
            str(partial),
        )
        process = subprocess.Popen(  # noqa: S603 - fixed executable and structured validated argv.
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        while process.poll() is None:
            if cancelled():
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                raise ArchiveCancelled("archive cancelled during transcode")
            time.sleep(0.05)
        stderr = process.stderr.read() if process.stderr is not None else ""
        if process.returncode != 0:
            raise ArchiveTransactionError(stderr.strip() or "ffmpeg archive transcode failed")


class ArchiveTransactionManager:
    """Owns all archive file, FFmpeg, manifest, checksum, and catalogue effects.

    Partial files are intentionally retained in `.archive-work` after failure/cancellation so a
    restart can show the user exactly what needs review; they are never published as media.
    """

    def __init__(
        self,
        catalogue: SQLiteLibraryCatalogue,
        *,
        verifier: FfprobeVerifier | None = None,
        checksums: Sha256Service | None = None,
        publisher: AtomicPublisher | None = None,
        copier: CrossFilesystemCopier | None = None,
        transcoder: FfmpegArchiveTranscoder | None = None,
        step_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._catalogue = catalogue
        self._verifier = verifier or FfprobeVerifier()
        self._checksums = checksums or Sha256Service()
        self._publisher = publisher or AtomicPublisher()
        self._copier = copier or CrossFilesystemCopier(self._checksums)
        self._transcoder = transcoder or FfmpegArchiveTranscoder()
        self._step_hook = step_hook or (lambda _step: None)
        self._lock = RLock()
        self._cancelled: dict[str, Event] = {}

    def enqueue(self, request: ArchiveRequest) -> tuple[ArchiveJobView, ...]:
        root = Path(request.archive_root).expanduser()
        if not root.is_absolute():
            raise ValueError("archive destination must be absolute")
        jobs: list[ArchiveJobView] = []
        with self._lock:
            for item_id in dict.fromkeys(request.source_item_ids):
                source = self._catalogue.archive_source(item_id)
                job_id = str(uuid4())
                destination = self._destination(root, Path(source.file_path or ""), job_id)
                if destination.exists():
                    raise ArchiveTransactionError(f"refusing to overwrite archive: {destination}")
                work = root / ".archive-work" / f"{job_id}.partial"
                job = self._catalogue.create_archive_job(
                    job_id,
                    source,
                    destination,
                    work,
                    request.profile.kind,
                    request.delete_sources_after_commit,
                )
                self._write_journal(job, "queued")
                jobs.append(job)
        return tuple(jobs)

    def jobs(self) -> tuple[ArchiveJobView, ...]:
        return self._catalogue.archive_jobs()

    def run_next(self) -> ArchiveJobView | None:
        with self._lock:
            next_job = next(
                (job for job in self.jobs() if job.state is ArchiveJobStateView.QUEUED), None
            )
            if next_job is None:
                return None
            event = self._cancelled.setdefault(next_job.job_id, Event())
        try:
            return self._run(next_job, event)
        finally:
            with self._lock:
                self._cancelled.pop(next_job.job_id, None)

    def pause(self, job_id: str) -> ArchiveJobView:
        with self._lock:
            job = self._catalogue.archive_job(job_id)
            if job.state not in {ArchiveJobStateView.QUEUED, ArchiveJobStateView.PRECHECK}:
                raise ArchiveTransactionError("only queued archive jobs can be paused")
            updated = self._catalogue.update_archive_job(job_id, ArchiveJobStateView.PAUSED)
            self._write_journal(updated, "paused")
            return updated

    def resume(self, job_id: str) -> ArchiveJobView:
        with self._lock:
            job = self._catalogue.archive_job(job_id)
            if job.state is not ArchiveJobStateView.PAUSED:
                raise ArchiveTransactionError("only paused archive jobs can be resumed")
            updated = self._catalogue.update_archive_job(job_id, ArchiveJobStateView.QUEUED)
            self._write_journal(updated, "queued")
            return updated

    def cancel(self, job_id: str) -> ArchiveJobView:
        with self._lock:
            job = self._catalogue.archive_job(job_id)
            if job.state in {ArchiveJobStateView.COMMITTED, ArchiveJobStateView.CANCELLED}:
                raise ArchiveTransactionError("completed archive jobs cannot be cancelled")
            event = self._cancelled.get(job_id)
            if event is not None:
                event.set()
                return job
            updated = self._catalogue.update_archive_job(
                job_id,
                ArchiveJobStateView.CANCELLED,
                restore_source_state=True,
            )
            self._write_journal(updated, "cancelled")
            return updated

    def retry(self, job_id: str) -> ArchiveJobView:
        with self._lock:
            job = self._catalogue.archive_job(job_id)
            if job.state not in {ArchiveJobStateView.FAILED, ArchiveJobStateView.CANCELLED}:
                raise ArchiveTransactionError(
                    "only failed or cancelled archive jobs can be retried"
                )
            updated = self._catalogue.update_archive_job(
                job_id,
                ArchiveJobStateView.QUEUED,
                progress_percent=0,
                restore_source_state=False,
            )
            self._write_journal(updated, "queued")
            return updated

    def recover_partials(self) -> tuple[ArchiveJobView, ...]:
        """Make every unfinished durable job visible; recovery never auto-publishes or deletes."""
        recovered: list[ArchiveJobView] = []
        with self._lock:
            for job in self.jobs():
                if job.state in {
                    ArchiveJobStateView.COMMITTED,
                    ArchiveJobStateView.CANCELLED,
                    ArchiveJobStateView.FAILED,
                }:
                    continue
                updated = self._catalogue.update_archive_job(
                    job.job_id,
                    ArchiveJobStateView.FAILED,
                    failure_code="recovery_partial_transaction",
                    failure_detail="application stopped before archive commit; source retained",
                    restore_source_state=True,
                )
                self._write_journal(updated, "recovery_partial_transaction")
                recovered.append(updated)
        return tuple(recovered)

    def select_session(self, session_id: str) -> tuple[str, ...]:
        if not session_id:
            raise ValueError("session ID is required")
        return self._catalogue.eligible_original_ids(session_id=session_id)

    def select_oldest_for_space(self, requested_bytes: int) -> tuple[str, ...]:
        return self._catalogue.eligible_original_ids(requested_bytes=requested_bytes)

    def move_to_active_library(self, item_id: str, active_root: Path) -> LibraryItem:
        with self._lock:
            item = self._catalogue._find_item(item_id)
            if item.media_class != "archive" or item.file_path is None:
                raise ArchiveTransactionError(
                    "only verified archives can move to the active library"
                )
            source = Path(item.file_path)
            self._confirm_media(source, source, expect_video=True, expect_audio=False)
            destination = active_root / "active-archives" / source.name
            if destination.exists():
                raise ArchiveTransactionError(
                    f"refusing to overwrite active-library item: {destination}"
                )
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if _same_filesystem(source, destination.parent):
                os.replace(source, destination)
                _fsync_directory(destination.parent)
                _fsync_directory(source.parent)
            else:
                self._copier.copy_and_verify(source, destination)
                source.unlink()
                _fsync_directory(source.parent)
            return self._catalogue.relocate_archive(item_id, destination)

    def create_share_copy(self, item_id: str, destination: Path) -> LibraryItem:
        with self._lock:
            source = self._catalogue._find_item(item_id)
            if (
                source.kind != "media"
                or source.file_path is None
                or source.validation_state != "verified"
            ):
                raise ArchiveTransactionError("only verified media can create a share copy")
            destination = destination.expanduser()
            if not destination.is_absolute() or destination.suffix != ".mkv":
                raise ValueError("share-copy destination must be an absolute MKV path")
            checksum = self._copier.copy_and_verify(Path(source.file_path), destination)
            return self._catalogue.add_derived_copy(source, destination, checksum)

    def _run(self, job: ArchiveJobView, cancelled: Event) -> ArchiveJobView:
        try:
            self._set(job, ArchiveJobStateView.PRECHECK, 2, "precheck")
            source = self._catalogue.archive_job_source(job.job_id)
            source_path = Path(source.file_path or "")
            destination = Path(job.destination_path)
            partial = Path(job.destination_path).with_name(
                f".{destination.name}.{job.job_id}.partial"
            )
            self._check_cancelled(cancelled)
            self._step("1-confirm-source")
            source_media = self._confirm_source(source_path)
            self._step("2-working-space")
            self._ensure_space(source_path, destination.parent, job.profile)
            self._step("3-lock-source")
            with _source_lock(source_path):
                original_checksum = self._checksums.digest_file(source_path)
                if job.profile is ArchiveProfileKind.COMPRESSED:
                    self._set(job, ArchiveJobStateView.TRANSCODING, 10, "transcoding")
                    self._step("4-write-partial")
                    partial.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    self._step("5-transcode-video")
                    self._transcoder.transcode(
                        source_path,
                        partial,
                        900,
                        cancelled.is_set,
                    )
                    self._step("6-copy-audio")
                else:
                    self._set(
                        job, ArchiveJobStateView.TRANSCODING, 10, "copying without compression"
                    )
                    self._step("4-write-partial")
                    self._check_cancelled(cancelled)
                    partial.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    self._copier.copy_and_verify(source_path, partial)
                    self._step("5-transcode-video")
                    self._step("6-copy-audio")
                self._check_cancelled(cancelled)
                self._set(job, ArchiveJobStateView.FLUSHING, 55, "flushing output")
                self._step("7-flush-close")
                self._fsync_file(partial)
                self._step("8-fsync-output")
                _fsync_directory(partial.parent)
                self._set(job, ArchiveJobStateView.VALIDATING, 60, "validating archive")
                self._step("9-ffprobe")
                archive_media = self._verifier.verify(
                    partial,
                    expect_video=source_media.video_streams > 0,
                    expect_audio=source_media.audio_streams > 0,
                )
                self._step("10-full-decode")
                self._verifier.verify_full_decode(partial)
                self._step("11-compare-streams-duration")
                self._compare_media(source_media, archive_media, job.profile)
                if source_media.audio_streams and (
                    self._verifier.audio_packet_hashes(source_path)
                    != self._verifier.audio_packet_hashes(partial)
                ):
                    raise ArchiveTransactionError("archive audio packets do not match the source")
                self._step("12-checksum")
                archive_checksum = self._checksums.digest_file(partial)
                if job.profile is ArchiveProfileKind.MOVE and archive_checksum != original_checksum:
                    raise ArchiveTransactionError("move archive checksum does not match source")
                if self._checksums.digest_file(source_path) != original_checksum:
                    raise ArchiveTransactionError(
                        "source changed while archive transaction was running"
                    )
                self._check_cancelled(cancelled)
                self._set(job, ArchiveJobStateView.PUBLISHING, 85, "publishing archive")
                self._step("13-publish")
                if destination.exists():
                    raise ArchiveTransactionError("archive destination appeared during transaction")
                os.replace(partial, destination)
                _fsync_directory(destination.parent)
                self._step("14-commit-catalogue-manifest")
                self._write_archive_manifest(
                    job, source, destination, archive_media, archive_checksum
                )
                committed = self._catalogue.commit_archive(
                    job.job_id,
                    archive_id=f"archive:{uuid4()}",
                    checksum=archive_checksum,
                    size=destination.stat().st_size,
                    duration_seconds=archive_media.duration_seconds,
                    video_codec=archive_media.video_codec,
                    audio_codec=archive_media.audio_codec,
                    delete_source=False,
                )
                self._write_journal(committed, "committed")
                self._step("15-delete-source")
                if job.delete_source_after_commit:
                    source_path.unlink()
                    _fsync_directory(source_path.parent)
                    self._catalogue.mark_source_deleted(job.job_id)
                return self._catalogue.archive_job(job.job_id)
        except ArchiveCancelled as error:
            updated = self._catalogue.update_archive_job(
                job.job_id,
                ArchiveJobStateView.CANCELLED,
                failure_code="cancelled",
                failure_detail=str(error),
                restore_source_state=True,
            )
            self._write_journal(updated, "cancelled")
            return updated
        except (
            ArchiveTransactionError,
            AtomicPublishError,
            MediaVerificationError,
            OSError,
        ) as error:
            updated = self._catalogue.update_archive_job(
                job.job_id,
                ArchiveJobStateView.FAILED,
                failure_code=_failure_code(error),
                failure_detail=str(error),
                restore_source_state=True,
            )
            self._write_journal(updated, "failed")
            return updated
        except Exception as error:
            # Infrastructure boundaries turn unexpected failures into an auditable safe failure.
            updated = self._catalogue.update_archive_job(
                job.job_id,
                ArchiveJobStateView.FAILED,
                failure_code="unexpected_archive_error",
                failure_detail=f"{type(error).__name__}: {error}",
                restore_source_state=True,
            )
            self._write_journal(updated, "failed")
            return updated

    def _set(
        self, job: ArchiveJobView, state: ArchiveJobStateView, progress: int, stage: str
    ) -> None:
        updated = self._catalogue.update_archive_job(job.job_id, state, progress_percent=progress)
        self._write_journal(updated, stage)

    def _confirm_source(self, source: Path) -> VerifiedMedia:
        if not source.is_file():
            raise ArchiveTransactionError("source is missing or not closed")
        first = source.stat()
        media = self._verifier.verify(source)
        self._verifier.verify_full_decode(source)
        second = source.stat()
        if (first.st_size, first.st_mtime_ns) != (second.st_size, second.st_mtime_ns):
            raise ArchiveTransactionError("source changed during precheck")
        return media

    def _ensure_space(
        self, source: Path, destination_directory: Path, profile: ArchiveProfileKind
    ) -> None:
        destination_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        required = (
            source.stat().st_size
            if profile is ArchiveProfileKind.MOVE
            else source.stat().st_size * 2
        )
        available = shutil.disk_usage(destination_directory).free
        if available < required:
            raise ArchiveTransactionError("insufficient archive working space")

    def _confirm_media(
        self, source: Path, output: Path, *, expect_video: bool, expect_audio: bool
    ) -> None:
        self._verifier.verify(source, expect_video=expect_video, expect_audio=expect_audio)
        self._verifier.verify_full_decode(output)

    @staticmethod
    def _compare_media(
        source: VerifiedMedia, archive: VerifiedMedia, profile: ArchiveProfileKind
    ) -> None:
        if (
            source.video_streams != archive.video_streams
            or source.audio_streams != archive.audio_streams
        ):
            raise ArchiveTransactionError("archive stream count does not match source")
        if abs(source.duration_seconds - archive.duration_seconds) > max(
            0.5, source.duration_seconds * 0.02
        ):
            raise ArchiveTransactionError("archive duration differs from source")
        if source.audio_streams and source.audio_codec != archive.audio_codec:
            raise ArchiveTransactionError("archive audio is not the source encoded audio stream")

    def _write_archive_manifest(
        self,
        job: ArchiveJobView,
        source: LibraryItem,
        destination: Path,
        media: VerifiedMedia,
        checksum: str,
    ) -> None:
        document = {
            "schema_version": 1,
            "archive_job_id": job.job_id,
            "source_segment_id": source.item_id,
            "source_path": source.file_path,
            "archive_path": str(destination),
            "profile": job.profile.value,
            "duration_seconds": media.duration_seconds,
            "video_codec": media.video_codec,
            "audio_codec": media.audio_codec,
            "sha256": checksum,
            "created_at": datetime.now(UTC).isoformat(),
        }
        path = destination.with_suffix(".archive-manifest.json")
        self._publisher.publish_bytes(
            path,
            (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            replace=False,
        )

    def _write_journal(self, job: ArchiveJobView, stage: str) -> None:
        work = Path(job.destination_path).parents[4] / ".archive-work"
        path = work / f"{job.job_id}.json"
        document = {
            "schema_version": 1,
            "job_id": job.job_id,
            "state": job.state.value,
            "stage": stage,
            "source_path": job.source_path,
            "destination_path": job.destination_path,
            "profile": job.profile.value,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._publisher.publish_bytes(
            path,
            (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            replace=True,
        )

    @staticmethod
    def _destination(root: Path, source: Path, job_id: str) -> Path:
        day = datetime.now().astimezone().strftime("%Y/%m/%d")
        return root / "archives" / day / f"{source.stem}.{job_id[:8]}.archive.mkv"

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with path.open("rb") as stream:
            os.fsync(stream.fileno())

    def _step(self, name: str) -> None:
        self._step_hook(name)

    @staticmethod
    def _check_cancelled(cancelled: Event) -> None:
        if cancelled.is_set():
            raise ArchiveCancelled("archive cancelled")


@contextmanager
def _source_lock(path: Path) -> Iterator[None]:
    with path.open("rb") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _same_filesystem(source: Path, destination_directory: Path) -> bool:
    return source.stat().st_dev == destination_directory.stat().st_dev


def _failure_code(error: BaseException) -> str:
    if isinstance(error, MediaVerificationError):
        return "media_validation_failed"
    if isinstance(error, AtomicPublishError):
        return "durable_publication_failed"
    if isinstance(error, OSError):
        return "filesystem_error"
    return "archive_transaction_failed"
