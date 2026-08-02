"""Phase 9 archive queue, transaction, recovery, and derived-copy coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from threading import Event, Thread
from time import sleep

import pytest

from usb_cctv_recorder.application.archive import ArchiveService
from usb_cctv_recorder.application.dto import (
    ArchiveJobStateView,
    ArchiveJobView,
    ArchiveProfile,
    ArchiveProfileKind,
    ArchiveRequest,
    LibraryFilter,
    LibraryItem,
)
from usb_cctv_recorder.infrastructure.commands.runner import CommandResult
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import (
    FfprobeVerifier,
    MediaVerificationError,
    VerifiedMedia,
    _optional_int,
)
from usb_cctv_recorder.infrastructure.persistence.library_catalogue import SQLiteLibraryCatalogue
from usb_cctv_recorder.infrastructure.persistence.sqlite import SQLiteCatalogue
from usb_cctv_recorder.infrastructure.storage.archive_transaction import (
    ArchiveCancelled,
    ArchiveTransactionError,
    ArchiveTransactionManager,
    FfmpegArchiveTranscoder,
    _failure_code,
)
from usb_cctv_recorder.infrastructure.storage.atomic_files import AtomicPublishError
from usb_cctv_recorder.infrastructure.storage.checksums import Sha256Service
from usb_cctv_recorder.presentation.qt.pages.archive_page import ArchivePage


class _Verifier:
    def __init__(
        self,
        *,
        output_failure: str | None = None,
        duration_delta: float = 0.0,
        output_audio_streams: int = 1,
        packet_mismatch: bool = False,
    ) -> None:
        self.output_failure = output_failure
        self.duration_delta = duration_delta
        self.output_audio_streams = output_audio_streams
        self.packet_mismatch = packet_mismatch

    def verify(self, path: Path, **_kwargs: object) -> VerifiedMedia:
        if self.output_failure and path.name.endswith(".partial"):
            raise MediaVerificationError(self.output_failure)
        duration = 3.0 + (self.duration_delta if path.name.endswith(".partial") else 0.0)
        return VerifiedMedia(
            path,
            duration,
            "h264",
            "aac",
            1,
            self.output_audio_streams if path.name.endswith(".partial") else 1,
            320,
            240,
            48000,
            1,
        )

    def verify_full_decode(self, path: Path) -> None:
        if self.output_failure == "decode failure" and path.name.endswith(".partial"):
            raise MediaVerificationError("decode failure")

    def audio_packet_hashes(self, path: Path) -> tuple[str, ...]:
        if self.packet_mismatch and path.name.endswith(".partial"):
            return ("sha256:changed",)
        return ("sha256:audio",)


class _Transcoder:
    def __init__(self, *, mutate: bool = False) -> None:
        self.mutate = mutate

    def transcode(self, source: Path, partial: Path, _bitrate: int, cancelled: object) -> None:
        if callable(cancelled) and cancelled():
            raise ArchiveTransactionError("cancelled")
        partial.write_bytes(b"archive" if self.mutate else source.read_bytes())


class _FailingCopier:
    def copy_and_verify(self, _source: Path, _destination: Path) -> str:
        raise AtomicPublishError("destination disconnected")


class _BlockingTranscoder:
    def __init__(self) -> None:
        self.started = Event()

    def transcode(self, _source: Path, _partial: Path, _bitrate: int, cancelled: object) -> None:
        self.started.set()
        while callable(cancelled) and not cancelled():
            sleep(0.01)
        raise ArchiveCancelled("archive cancelled during transcode")


def _write_session(root: Path) -> Path:
    session = root / "originals" / "2026-08-02" / "session-fixture"
    session.mkdir(parents=True)
    source = session / "segment-000000.mkv"
    source.write_bytes(b"authoritative original bytes")
    checksum = Sha256Service().digest_file(source)
    (session / "session.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": "6a96b607-08cb-4b72-b282-84b816ef6f5d",
                "state": "completed",
                "created_at": "2026-08-02T10:00:00+00:00",
                "updated_at": "2026-08-02T10:10:00+00:00",
                "segment_ids": ["segment-1"],
                "segments": [
                    {
                        "segment_id": "segment-1",
                        "filename": source.name,
                        "duration_seconds": 3.0,
                        "sha256": checksum,
                    }
                ],
                "stop_reason": "user_requested",
                "failure_reason": None,
            }
        )
    )
    return source


def _manager(tmp_path: Path, **kwargs: object) -> ArchiveTransactionManager:
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(tmp_path / "state" / "catalogue.sqlite"))
    catalogue.rebuild(tmp_path / "media")
    return ArchiveTransactionManager(catalogue, verifier=_Verifier(), **kwargs)  # type: ignore[arg-type]


def _enqueue(
    manager: ArchiveTransactionManager, root: Path, *, move: bool = False, delete: bool = False
):
    return manager.enqueue(
        ArchiveRequest(
            ("segment-1",),
            ArchiveProfile(ArchiveProfileKind.MOVE if move else ArchiveProfileKind.COMPRESSED),
            str(root),
            delete,
        )
    )[0]


def test_compressed_archive_is_fully_committed_without_changing_source(tmp_path: Path) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    before = source.read_bytes()
    manager = _manager(tmp_path, transcoder=_Transcoder(mutate=True))

    job = _enqueue(manager, root)
    completed = manager.run_next()

    assert completed is not None and completed.state is ArchiveJobStateView.COMMITTED
    assert source.read_bytes() == before
    archive = Path(completed.destination_path)
    assert archive.read_bytes() == b"archive"
    manifest = archive.with_suffix(".archive-manifest.json")
    assert json.loads(manifest.read_text())["source_segment_id"] == "segment-1"
    assert manager._catalogue.page(LibraryFilter(media_class="archive"), 0, 10)[0].file_path == str(
        archive
    )
    assert job.destination_path == completed.destination_path


def test_delete_waits_for_commit_and_catalogue_rebuild_hides_deleted_source(tmp_path: Path) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    manager = _manager(tmp_path, transcoder=_Transcoder())

    job = _enqueue(manager, root, delete=True)
    completed = manager.run_next()

    assert completed is not None and completed.state is ArchiveJobStateView.COMMITTED
    assert not source.exists()
    manager._catalogue.rebuild(root)
    items = manager._catalogue.page(LibraryFilter(), 0, 10)
    assert [item.media_class for item in items] == ["archive"]
    assert Path(job.destination_path).is_file()


@pytest.mark.parametrize(
    "step",
    (
        "1-confirm-source",
        "2-working-space",
        "3-lock-source",
        "4-write-partial",
        "5-transcode-video",
        "6-copy-audio",
        "7-flush-close",
        "8-fsync-output",
        "9-ffprobe",
        "10-full-decode",
        "11-compare-streams-duration",
        "12-checksum",
        "13-publish",
        "14-commit-catalogue-manifest",
        "15-delete-source",
    ),
)
def test_injected_failure_at_each_transaction_step_preserves_source(
    tmp_path: Path, step: str
) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    before = source.read_bytes()

    def fail_at(current: str) -> None:
        if current == step:
            raise ArchiveTransactionError(f"injected failure at {current}")

    manager = _manager(tmp_path, transcoder=_Transcoder(), step_hook=fail_at)
    _enqueue(manager, root, delete=True)
    result = manager.run_next()

    assert result is not None and result.state is ArchiveJobStateView.FAILED
    assert source.read_bytes() == before
    assert result.failure_detail is not None and step in result.failure_detail


def test_decode_duration_and_destination_failures_leave_source_untouched(tmp_path: Path) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    before = source.read_bytes()
    verifier = _Verifier(output_failure="decode failure")
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(tmp_path / "state" / "catalogue.sqlite"))
    catalogue.rebuild(root)
    manager = ArchiveTransactionManager(catalogue, verifier=verifier, transcoder=_Transcoder())
    _enqueue(manager, root, delete=True)
    result = manager.run_next()
    assert result is not None and result.state is ArchiveJobStateView.FAILED
    assert source.read_bytes() == before

    destination_root = tmp_path / "move-root"
    catalogue = SQLiteLibraryCatalogue(
        SQLiteCatalogue(tmp_path / "move-state" / "catalogue.sqlite")
    )
    catalogue.rebuild(root)
    manager = ArchiveTransactionManager(catalogue, verifier=_Verifier(), copier=_FailingCopier())  # type: ignore[arg-type]
    _enqueue(manager, destination_root, move=True, delete=True)
    result = manager.run_next()
    assert result is not None and result.failure_code == "durable_publication_failed"
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "verifier",
    (_Verifier(duration_delta=1.0), _Verifier(output_audio_streams=0)),
)
def test_duration_or_audio_validation_failure_preserves_source(
    tmp_path: Path, verifier: _Verifier
) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    before = source.read_bytes()
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(tmp_path / "state" / "catalogue.sqlite"))
    catalogue.rebuild(root)
    manager = ArchiveTransactionManager(catalogue, verifier=verifier, transcoder=_Transcoder())
    _enqueue(manager, root, delete=True)

    result = manager.run_next()

    assert result is not None and result.state is ArchiveJobStateView.FAILED
    assert source.read_bytes() == before


def test_audio_packet_mismatch_preserves_source(tmp_path: Path) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    before = source.read_bytes()
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(tmp_path / "state" / "catalogue.sqlite"))
    catalogue.rebuild(root)
    manager = ArchiveTransactionManager(
        catalogue, verifier=_Verifier(packet_mismatch=True), transcoder=_Transcoder()
    )
    _enqueue(manager, root, delete=True)

    result = manager.run_next()

    assert result is not None and result.state is ArchiveJobStateView.FAILED
    assert result.failure_detail == "archive audio packets do not match the source"
    assert source.read_bytes() == before


def test_existing_destination_and_terminal_recovery_never_remove_source(tmp_path: Path) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    before = source.read_bytes()
    manager = _manager(tmp_path, transcoder=_Transcoder())
    job = _enqueue(manager, root)
    destination = Path(job.destination_path)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing evidence")

    result = manager.run_next()

    assert result is not None and result.state is ArchiveJobStateView.FAILED
    assert source.read_bytes() == before
    assert manager.recover_partials() == ()


def test_recovery_and_derived_share_copy_never_mutate_authoritative_media(tmp_path: Path) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    before = source.read_bytes()
    manager = _manager(tmp_path, transcoder=_Transcoder())
    queued = _enqueue(manager, root)
    manager._catalogue.update_archive_job(queued.job_id, ArchiveJobStateView.TRANSCODING)

    recovered = manager.recover_partials()

    assert recovered[0].failure_code == "recovery_partial_transaction"
    assert source.read_bytes() == before


def test_cancel_during_transcode_preserves_source_and_never_publishes(tmp_path: Path) -> None:
    root = tmp_path / "media"
    source = _write_session(root)
    before = source.read_bytes()
    transcoder = _BlockingTranscoder()
    manager = _manager(tmp_path, transcoder=transcoder)
    job = _enqueue(manager, root, delete=True)
    result: list[object] = []
    thread = Thread(target=lambda: result.append(manager.run_next()))
    thread.start()
    assert transcoder.started.wait(timeout=1)
    manager.cancel(job.job_id)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert result[0].state is ArchiveJobStateView.CANCELLED  # type: ignore[union-attr]
    assert source.read_bytes() == before
    assert not Path(job.destination_path).exists()
    service = ArchiveService(manager)
    share = service.create_share_copy("segment-1", tmp_path / "share" / "copy.mkv")
    assert share.media_class == "share_copy"
    assert Path(share.file_path or "").read_bytes() == before
    assert source.read_bytes() == before


def test_manual_session_and_requested_space_selection_exclude_ineligible_media(
    tmp_path: Path,
) -> None:
    root = tmp_path / "media"
    _write_session(root)
    manager = _manager(tmp_path, transcoder=_Transcoder())

    assert manager.select_session("6a96b607-08cb-4b72-b282-84b816ef6f5d") == ("segment-1",)
    assert manager.select_oldest_for_space(1) == ("segment-1",)
    manager._catalogue.set_protected("segment-1", True)
    assert manager.select_oldest_for_space(1) == ()


def test_queue_controls_and_active_library_move_are_explicit(tmp_path: Path) -> None:
    root = tmp_path / "media"
    _write_session(root)
    manager = _manager(tmp_path, transcoder=_Transcoder())
    job = _enqueue(manager, root)

    assert manager.pause(job.job_id).state is ArchiveJobStateView.PAUSED
    assert manager.resume(job.job_id).state is ArchiveJobStateView.QUEUED
    assert manager.cancel(job.job_id).state is ArchiveJobStateView.CANCELLED
    assert manager.retry(job.job_id).state is ArchiveJobStateView.QUEUED
    completed = manager.run_next()
    assert completed is not None and completed.state is ArchiveJobStateView.COMMITTED
    assert manager.run_next() is None

    archive = manager._catalogue.page(LibraryFilter(media_class="archive"), 0, 1)[0]
    moved = manager.move_to_active_library(archive.item_id, root)
    assert moved.media_class == "archive"
    assert "active-archives" in (moved.file_path or "")
    with pytest.raises(ArchiveTransactionError, match="completed"):
        manager.cancel(job.job_id)


def test_archive_guards_and_unexpected_failure_are_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "media"
    _write_session(root)
    manager = _manager(tmp_path, transcoder=_Transcoder())
    with pytest.raises(ValueError, match="absolute"):
        manager.enqueue(
            ArchiveRequest(
                ("segment-1",), ArchiveProfile(ArchiveProfileKind.COMPRESSED), "relative"
            )
        )
    with pytest.raises(ArchiveTransactionError, match="missing"):
        manager._confirm_source(tmp_path / "missing.mkv")
    with pytest.raises(ArchiveTransactionError, match="space"):
        monkeypatch.setattr(
            "usb_cctv_recorder.infrastructure.storage.archive_transaction.shutil.disk_usage",
            lambda _path: type("Usage", (), {"free": 0})(),
        )
        manager._ensure_space(
            root / "originals" / "2026-08-02" / "session-fixture" / "segment-000000.mkv",
            root,
            ArchiveProfileKind.MOVE,
        )
    assert _failure_code(OSError("disconnect")) == "filesystem_error"
    job = _enqueue(manager, root)
    manager._step_hook = lambda _step: (_ for _ in ()).throw(ValueError("unexpected"))
    result = manager.run_next()
    assert result is not None and result.failure_code == "unexpected_archive_error"
    assert manager.retry(job.job_id).state is ArchiveJobStateView.QUEUED
    with pytest.raises(ArchiveTransactionError, match="paused"):
        manager.resume(job.job_id)
    assert manager.pause(job.job_id).state is ArchiveJobStateView.PAUSED
    with pytest.raises(ArchiveTransactionError, match="queued"):
        manager.pause(job.job_id)
    assert manager.resume(job.job_id).state is ArchiveJobStateView.QUEUED
    with pytest.raises(ArchiveTransactionError, match="failed"):
        manager.retry(job.job_id)
    with pytest.raises(ValueError, match="session ID"):
        manager.select_session("")
    with pytest.raises(ArchiveTransactionError, match="active library"):
        manager.move_to_active_library("segment-1", root)
    with pytest.raises(ValueError, match="absolute MKV"):
        manager.create_share_copy("segment-1", Path("relative.mkv"))
    manager._check_cancelled(Event())
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ArchiveCancelled):
        manager._check_cancelled(cancelled)
    source_media = _Verifier().verify(root / "source.mkv")
    different_audio = VerifiedMedia(
        root / "archive.mkv", 3.0, "h264", "opus", 1, 1, 320, 240, 48000, 1
    )
    with pytest.raises(ArchiveTransactionError, match="audio"):
        manager._compare_media(source_media, different_audio, ArchiveProfileKind.COMPRESSED)


def test_transcoder_gracefully_cancels_or_reports_ffmpeg_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Process:
        def __init__(self, returncode: int | None, stderr: str = "") -> None:
            self.returncode = returncode
            self.stderr = type("Stderr", (), {"read": lambda _self: stderr})()
            self.terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout: int) -> int:
            assert timeout == 10
            return 0

        def kill(self) -> None:
            self.returncode = -9

    process = _Process(None)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    with pytest.raises(ArchiveCancelled):
        FfmpegArchiveTranscoder().transcode(
            tmp_path / "source", tmp_path / "partial", 900, lambda: True
        )
    assert process.terminated

    failed = _Process(1, "encode failed")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: failed)
    with pytest.raises(ArchiveTransactionError, match="encode failed"):
        FfmpegArchiveTranscoder().transcode(
            tmp_path / "source", tmp_path / "partial", 900, lambda: False
        )


def test_audio_packet_hash_verification_rejects_failed_empty_and_invalid_probe_output() -> None:
    class _Runner:
        def __init__(self, result: CommandResult) -> None:
            self.result = result

        def run(self, _arguments: tuple[str, ...]) -> CommandResult:
            return self.result

    success = CommandResult(("ffprobe",), 0, '{"packets":[{"data_hash":"SHA256:x"}]}', "")
    assert FfprobeVerifier(_Runner(success)).audio_packet_hashes(Path("audio.mkv")) == ("SHA256:x",)  # type: ignore[arg-type]
    failed = CommandResult(("ffprobe",), 1, "", "unavailable")
    with pytest.raises(MediaVerificationError, match="unavailable"):
        FfprobeVerifier(_Runner(failed)).audio_packet_hashes(Path("audio.mkv"))  # type: ignore[arg-type]
    malformed = CommandResult(("ffprobe",), 0, '{"packets":[{}]}', "")
    with pytest.raises(MediaVerificationError, match="incomplete"):
        FfprobeVerifier(_Runner(malformed)).audio_packet_hashes(Path("audio.mkv"))  # type: ignore[arg-type]
    empty = CommandResult(("ffprobe",), 0, '{"packets":[]}', "")
    with pytest.raises(MediaVerificationError, match="no encoded"):
        FfprobeVerifier(_Runner(empty)).audio_packet_hashes(Path("audio.mkv"))  # type: ignore[arg-type]
    assert _optional_int(object()) is None
    assert _optional_int("not-an-int") is None


class _ArchivePort:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.job = ArchiveJobView(
            "job",
            "source",
            "/tmp/source.mkv",
            "/tmp/archives/2026/08/02/archive.mkv",
            ArchiveProfileKind.COMPRESSED,
            ArchiveJobStateView.QUEUED,
            False,
            0,
            None,
            None,
        )

    def enqueue(self, request: ArchiveRequest) -> tuple[ArchiveJobView, ...]:
        self.calls.append(f"enqueue:{len(request.source_item_ids)}")
        return (self.job,)

    def jobs(self) -> tuple[ArchiveJobView, ...]:
        self.calls.append("jobs")
        return (self.job,)

    def run_next(self) -> ArchiveJobView:
        self.calls.append("run")
        return self.job

    def pause(self, _job_id: str) -> ArchiveJobView:
        self.calls.append("pause")
        return self.job

    def resume(self, _job_id: str) -> ArchiveJobView:
        self.calls.append("resume")
        return self.job

    def cancel(self, _job_id: str) -> ArchiveJobView:
        self.calls.append("cancel")
        return self.job

    def retry(self, _job_id: str) -> ArchiveJobView:
        self.calls.append("retry")
        return self.job

    def recover_partials(self) -> tuple[ArchiveJobView, ...]:
        self.calls.append("recover")
        return (self.job,)

    def select_session(self, _session_id: str) -> tuple[str, ...]:
        self.calls.append("session")
        return ("source",)

    def select_oldest_for_space(self, _requested_bytes: int) -> tuple[str, ...]:
        self.calls.append("space")
        return ("source",)

    def move_to_active_library(self, _item_id: str, _active_root: Path) -> LibraryItem:
        self.calls.append("move")
        return _library_item()

    def create_share_copy(self, _item_id: str, _destination: Path) -> LibraryItem:
        self.calls.append("share")
        return _library_item()


def test_archive_service_and_qt_queue_controls(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    port = _ArchivePort()
    service = ArchiveService(port)  # type: ignore[arg-type]
    page = ArchivePage(service, tmp_path)
    qtbot.addWidget(page)
    page.set_library_selection(("source",))
    page._enqueue()
    qtbot.waitUntil(lambda: "enqueue:1" in port.calls)
    page._select_session()
    assert "session ID" in page.status.text()
    page.session_id.setText("session")
    page._select_session()
    qtbot.waitUntil(lambda: "session" in port.calls)
    page._select_oldest_for_space()
    qtbot.waitUntil(lambda: "space" in port.calls)
    page.table.selectRow(0)
    page._selected_action(service.pause)
    qtbot.waitUntil(lambda: "pause" in port.calls)
    page._selected_action(service.resume)
    qtbot.waitUntil(lambda: "resume" in port.calls)
    page._selected_action(service.cancel)
    qtbot.waitUntil(lambda: "cancel" in port.calls)
    page._selected_action(service.retry)
    qtbot.waitUntil(lambda: "retry" in port.calls)
    page._start(service.run_next)
    qtbot.waitUntil(lambda: "run" in port.calls)
    assert service.jobs() == (port.job,)
    assert service.enqueue(
        ArchiveRequest(("source",), ArchiveProfile(ArchiveProfileKind.COMPRESSED), str(tmp_path))
    ) == (port.job,)
    assert service.run_next() == port.job
    assert service.pause("job") == port.job
    assert service.resume("job") == port.job
    assert service.cancel("job") == port.job
    assert service.retry("job") == port.job
    assert service.recover_partials() == (port.job,)
    assert service.select_session("session") == ("source",)
    assert service.select_oldest_for_space(1) == ("source",)
    assert service.move_to_active_library("archive", tmp_path).media_class == "archive"
    assert service.create_share_copy("archive", tmp_path / "copy.mkv").media_class == "archive"
    assert {"jobs", "recover", "run", "pause", "resume", "cancel", "retry"} <= set(port.calls)


def _library_item() -> LibraryItem:
    return LibraryItem(
        "archive",
        "media",
        "session",
        "archive",
        "/tmp/archive.mkv",
        "2026-08-02T10:00:00+00:00",
        1.0,
        False,
        "verified",
        "none",
        "archived_verified",
        None,
    )
