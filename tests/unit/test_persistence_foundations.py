"""Phase 2 durable catalogue, manifest, journal, and storage adapter tests."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from usb_cctv_recorder.application.configuration import WorkerRecordingConfiguration
from usb_cctv_recorder.domain.states import SessionState
from usb_cctv_recorder.domain.value_objects import SessionId, UtcTimestamp
from usb_cctv_recorder.infrastructure.configuration import WorkerConfigurationStore, XdgPaths
from usb_cctv_recorder.infrastructure.persistence.event_journal import (
    JournalEvent,
    JsonlEventJournal,
)
from usb_cctv_recorder.infrastructure.persistence.manifest import (
    ManifestSegment,
    ManifestStore,
    SessionManifest,
)
from usb_cctv_recorder.infrastructure.persistence.migrations.versions import Migration
from usb_cctv_recorder.infrastructure.persistence.sqlite import MigrationError, SQLiteCatalogue
from usb_cctv_recorder.infrastructure.storage.atomic_files import (
    AtomicPublisher,
    AtomicPublishError,
    CrossFilesystemCopier,
)
from usb_cctv_recorder.infrastructure.storage.checksums import Sha256Service

NOW = UtcTimestamp(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))


def test_sqlite_migrates_forward_and_rolls_back(tmp_path: Path) -> None:
    catalogue = SQLiteCatalogue(tmp_path / "state" / "catalogue.sqlite3")
    try:
        assert catalogue.current_version() == 0
        catalogue.migrate()
        assert catalogue.current_version() == 4
        tables = {row[0] for row in catalogue.connection.execute("SELECT name FROM sqlite_master")}
        assert {"sessions", "segments", "archive_jobs", "recording_gaps"} <= tables
        columns = {
            row[1] for row in catalogue.connection.execute("PRAGMA table_info(archive_jobs)")
        }
        assert {"source_path", "destination_path", "profile", "failure_detail"} <= columns
        catalogue.rollback_last()
        assert catalogue.current_version() == 3
        catalogue.rollback_last()
        assert catalogue.current_version() == 2
        catalogue.rollback_last()
        assert catalogue.current_version() == 1
        catalogue.rollback_last()
        assert catalogue.current_version() == 0
        tables = {row[0] for row in catalogue.connection.execute("SELECT name FROM sqlite_master")}
        assert "sessions" not in tables
    finally:
        catalogue.close()


def test_sqlite_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    catalogue = SQLiteCatalogue(tmp_path / "catalogue.sqlite3")
    try:
        catalogue.migrate()
        with pytest.raises(sqlite3.IntegrityError):
            with catalogue.transaction():
                catalogue.connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?)", ("session", "idle", "now", "now")
                )
                catalogue.connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?)", ("session", "idle", "now", "now")
                )
        assert catalogue.connection.execute("SELECT COUNT(*) FROM sessions").fetchone() == (0,)
    finally:
        catalogue.close()


def test_sqlite_rejects_a_skipped_or_unknown_migration(tmp_path: Path) -> None:
    catalogue = SQLiteCatalogue(tmp_path / "catalogue.sqlite3")
    skipped = Migration(2, lambda _: None, lambda _: None)
    try:
        with pytest.raises(MigrationError, match="skips"):
            catalogue.migrate((skipped,))
        catalogue.connection.execute("INSERT INTO schema_migrations VALUES (9)")
        catalogue.connection.commit()
        with pytest.raises(MigrationError, match="no rollback"):
            catalogue.rollback_last()
    finally:
        catalogue.close()


def test_manifest_round_trip_and_atomic_store(tmp_path: Path) -> None:
    manifest = SessionManifest(
        session_id=SessionId.parse("123e4567-e89b-12d3-a456-426614174000"),
        state=SessionState.RECORDING_AV,
        created_at=NOW,
        updated_at=NOW,
        segment_ids=("segment-a",),
    )
    path = tmp_path / "session.json"
    store = ManifestStore()
    store.save(path, manifest)
    assert store.load(path) == manifest
    updated = SessionManifest(
        session_id=manifest.session_id,
        state=SessionState.COMPLETED,
        created_at=manifest.created_at,
        updated_at=NOW,
        segment_ids=manifest.segment_ids,
    )
    store.save(path, updated)
    assert store.load(path) == updated
    with pytest.raises(ValueError, match="invalid session manifest"):
        SessionManifest.from_json("{}")
    with pytest.raises(ValueError, match="unsupported"):
        SessionManifest(SessionId.new(), SessionState.IDLE, NOW, NOW, schema_version=2)
    segment = ManifestSegment("segment-a", "segment-000000.mkv", 1.5, "a" * 64)
    assert ManifestSegment.from_dict(segment.to_dict()) == segment
    with pytest.raises(ValueError, match="object"):
        ManifestSegment.from_dict("invalid")
    with pytest.raises(ValueError, match="invalid session manifest"):
        SessionManifest.from_json(
            '{"schema_version":1,"session_id":"123e4567-e89b-12d3-a456-426614174000",'
            '"state":"idle","created_at":"2026-08-01T12:00:00+00:00",'
            '"updated_at":"2026-08-01T12:00:00+00:00","stop_reason":5}'
        )


def test_event_journal_only_appends_and_round_trips(tmp_path: Path) -> None:
    journal = JsonlEventJournal(tmp_path / "events.jsonl")
    first = JournalEvent("session_started", NOW, {"source": "camera"})
    second = JournalEvent("segment_finalized", NOW, {"bytes": 12})
    journal.append(first)
    first_contents = journal.path.read_bytes()
    journal.append(second)
    assert journal.path.read_bytes().startswith(first_contents)
    assert journal.read_all() == (first, second)
    with pytest.raises(ValueError, match="event type"):
        JournalEvent("", NOW, {})
    with pytest.raises(ValueError, match="invalid event journal"):
        JournalEvent.from_json_line("not-json")
    with pytest.raises(ValueError, match="invalid event journal"):
        JournalEvent.from_json_line(
            '{"event_type":"x","occurred_at":"2026-08-01T12:00:00+00:00","payload":[]}'
        )


def test_atomic_publication_is_durable_and_keeps_no_partial_file_on_interruption(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "published.json"
    publisher = AtomicPublisher()
    publisher.publish_bytes(destination, b"complete")
    assert destination.read_bytes() == b"complete"
    with pytest.raises(AtomicPublishError, match="overwrite"):
        publisher.publish_bytes(destination, b"replacement")

    interrupted = tmp_path / "interrupted.json"

    def fail_after_partial_write(stream: object) -> None:
        stream.write(b"partial")  # type: ignore[union-attr]
        raise RuntimeError("simulated process interruption")

    with pytest.raises(AtomicPublishError, match="publication failed"):
        publisher.publish(interrupted, fail_after_partial_write)
    assert not interrupted.exists()
    assert not list(tmp_path.glob(".interrupted.json.*.tmp"))


class MismatchedChecksumService(Sha256Service):
    def __init__(self) -> None:
        self.calls = 0

    def digest_file(self, path: Path, chunk_size: int = 1024 * 1024) -> str:
        self.calls += 1
        return "a" * 64 if self.calls == 1 else "b" * 64


def test_cross_filesystem_copy_verifies_before_publication_and_keeps_source(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    destination = tmp_path / "other-filesystem" / "copy.mkv"
    source.write_bytes(b"authoritative bytes")
    copier = CrossFilesystemCopier()

    digest = copier.copy_and_verify(source, destination, chunk_size=3)
    assert digest == Sha256Service().digest_file(source)
    assert destination.read_bytes() == source.read_bytes()
    assert source.exists()
    with pytest.raises(AtomicPublishError, match="overwrite"):
        copier.copy_and_verify(source, destination)
    with pytest.raises(FileNotFoundError):
        copier.copy_and_verify(tmp_path / "missing", tmp_path / "missing-copy")
    with pytest.raises(ValueError, match="chunk size"):
        copier.copy_and_verify(source, tmp_path / "invalid", chunk_size=0)

    mismatch_destination = tmp_path / "mismatch.mkv"
    with pytest.raises(AtomicPublishError, match="checksum"):
        CrossFilesystemCopier(MismatchedChecksumService()).copy_and_verify(
            source, mismatch_destination
        )
    assert not mismatch_destination.exists()
    assert not list(tmp_path.glob(".mismatch.mkv.*.tmp"))


def test_sha256_uses_known_vector_and_streams_in_chunks(tmp_path: Path) -> None:
    path = tmp_path / "vector.bin"
    path.write_bytes(b"abc")
    service = Sha256Service()
    assert service.digest_file(path, chunk_size=1) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    with path.open("rb") as stream:
        assert service.digest_stream(stream) == service.digest_file(path)
    with pytest.raises(ValueError, match="chunk size"):
        service.digest_file(path, chunk_size=0)


def test_xdg_paths_resolve_and_create_private_directories(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    paths = XdgPaths.resolve(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_RUNTIME_DIR": str(runtime),
        }
    )
    paths.create_private_directories()
    assert paths.media == tmp_path / "home" / "Videos" / "USB-CCTV-Recorder"
    assert all(path.is_dir() for path in (paths.config, paths.state, paths.cache, paths.runtime))
    assert os.stat(paths.config).st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match="XDG_RUNTIME_DIR"):
        XdgPaths.resolve({"HOME": str(tmp_path)})


def test_worker_configuration_is_private_validated_and_round_trips(tmp_path: Path) -> None:
    paths = XdgPaths.resolve(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        }
    )
    store = WorkerConfigurationStore(paths)
    assert store.load() is None
    configuration = WorkerRecordingConfiguration(
        tmp_path / "media",
        "/dev/v4l/by-id/camera",
        "alsa_input.camera",
        2560,
        1440,
        30,
        15,
        60,
    )
    store.save(configuration)
    saved = paths.config / "worker-recording.json"
    assert store.load() == configuration
    assert saved.stat().st_mode & 0o777 == 0o600
    saved.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        store.load()
    saved.chmod(0o600)
    saved.write_text("{}")
    with pytest.raises(ValueError, match="fields"):
        store.load()
