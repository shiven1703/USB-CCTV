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


MIGRATIONS: tuple[Migration, ...] = (Migration(1, _create_catalogue, _drop_catalogue),)
