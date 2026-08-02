"""Ordered SQLite schema migrations for the recorder catalogue."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

MigrationAction = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    apply: MigrationAction
    rollback: MigrationAction


def _create_catalogue(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE segments (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            state TEXT NOT NULL,
            media_class TEXT NOT NULL,
            file_path TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            monotonic_duration_seconds REAL,
            width INTEGER,
            height INTEGER,
            frame_rate REAL,
            video_codec TEXT,
            audio_codec TEXT,
            streams_validated INTEGER NOT NULL DEFAULT 0,
            file_size_bytes INTEGER,
            sha256 TEXT,
            protected INTEGER NOT NULL DEFAULT 0,
            archive_source_segment_id TEXT REFERENCES segments(id),
            has_recording_gap INTEGER NOT NULL DEFAULT 0,
            error_state TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT,
            moved_at TEXT,
            deleted_at TEXT
        );
        CREATE TABLE archive_jobs (
            id TEXT PRIMARY KEY,
            segment_id TEXT NOT NULL REFERENCES segments(id),
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX segments_session_id_index ON segments(session_id);
        CREATE INDEX segments_archive_source_index ON segments(archive_source_segment_id);
        """
    )


def _drop_catalogue(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS archive_jobs;
        DROP TABLE IF EXISTS segments;
        DROP TABLE IF EXISTS sessions;
        """
    )


def _create_recovery_gaps(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE recording_gaps (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            reason TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_seconds REAL,
            attempts INTEGER NOT NULL,
            last_good_video_monotonic REAL,
            last_good_audio_monotonic REAL
        );
        CREATE INDEX recording_gaps_session_id_index ON recording_gaps(session_id);
        """
    )


def _drop_recovery_gaps(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS recording_gaps")


def _add_archive_transaction_details(connection: sqlite3.Connection) -> None:
    """Persist enough state to surface every interrupted archive after restart."""
    connection.executescript(
        """
        ALTER TABLE archive_jobs ADD COLUMN source_path TEXT;
        ALTER TABLE archive_jobs ADD COLUMN destination_path TEXT;
        ALTER TABLE archive_jobs ADD COLUMN work_path TEXT;
        ALTER TABLE archive_jobs ADD COLUMN profile TEXT;
        ALTER TABLE archive_jobs ADD COLUMN delete_source_after_commit INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE archive_jobs ADD COLUMN progress_percent INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE archive_jobs ADD COLUMN failure_code TEXT;
        ALTER TABLE archive_jobs ADD COLUMN failure_detail TEXT;
        """
    )


def _remove_archive_transaction_details(connection: sqlite3.Connection) -> None:
    # SQLite cannot drop columns on every supported baseline. Recreate the small job table.
    connection.executescript(
        """
        CREATE TABLE archive_jobs_previous (
            id TEXT PRIMARY KEY,
            segment_id TEXT NOT NULL REFERENCES segments(id),
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO archive_jobs_previous(id, segment_id, state, created_at, updated_at)
            SELECT id, segment_id, state, created_at, updated_at FROM archive_jobs;
        DROP TABLE archive_jobs;
        ALTER TABLE archive_jobs_previous RENAME TO archive_jobs;
        """
    )


def _make_archive_job_source_rebuild_safe(connection: sqlite3.Connection) -> None:
    """Catalogue rebuild is derived-state replacement; retained jobs keep their path journal."""
    connection.executescript(
        """
        CREATE TABLE archive_jobs_rebuilt (
            id TEXT PRIMARY KEY,
            segment_id TEXT REFERENCES segments(id) ON DELETE SET NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_path TEXT,
            destination_path TEXT,
            work_path TEXT,
            profile TEXT,
            delete_source_after_commit INTEGER NOT NULL DEFAULT 0,
            progress_percent INTEGER NOT NULL DEFAULT 0,
            failure_code TEXT,
            failure_detail TEXT
        );
        INSERT INTO archive_jobs_rebuilt SELECT * FROM archive_jobs;
        DROP TABLE archive_jobs;
        ALTER TABLE archive_jobs_rebuilt RENAME TO archive_jobs;
        """
    )


def _restore_archive_job_source_foreign_key(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE archive_jobs_previous (
            id TEXT PRIMARY KEY,
            segment_id TEXT NOT NULL REFERENCES segments(id),
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_path TEXT,
            destination_path TEXT,
            work_path TEXT,
            profile TEXT,
            delete_source_after_commit INTEGER NOT NULL DEFAULT 0,
            progress_percent INTEGER NOT NULL DEFAULT 0,
            failure_code TEXT,
            failure_detail TEXT
        );
        INSERT INTO archive_jobs_previous SELECT * FROM archive_jobs WHERE segment_id IS NOT NULL;
        DROP TABLE archive_jobs;
        ALTER TABLE archive_jobs_previous RENAME TO archive_jobs;
        """
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, _create_catalogue, _drop_catalogue),
    Migration(2, _create_recovery_gaps, _drop_recovery_gaps),
    Migration(3, _add_archive_transaction_details, _remove_archive_transaction_details),
    Migration(4, _make_archive_job_source_rebuild_safe, _restore_archive_job_source_foreign_key),
)
