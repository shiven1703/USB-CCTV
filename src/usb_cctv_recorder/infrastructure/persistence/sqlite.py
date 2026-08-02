"""SQLite migration and transaction primitives for authoritative catalogue changes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .migrations.versions import MIGRATIONS, Migration


class MigrationError(RuntimeError):
    """Raised when the persisted schema cannot be safely migrated."""


class SQLiteCatalogue:
    """Owns one SQLite connection and explicit transaction boundaries."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Presentation queries run in short-lived Qt worker threads. This adapter serializes
        # evidence operations at its callers; SQLite's connection must permit that hand-off.
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")
        self._create_migration_table()

    def close(self) -> None:
        self.connection.close()

    def _create_migration_table(self) -> None:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
        )
        self.connection.commit()

    def current_version(self) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
        assert row is not None
        return int(row[0])

    def migrate(self, migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
        current = self.current_version()
        for migration in migrations:
            if migration.version <= current:
                continue
            if migration.version != current + 1:
                raise MigrationError(
                    f"migration sequence skips from {current} to {migration.version}"
                )
            with self.transaction():
                migration.apply(self.connection)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)", (migration.version,)
                )
            current = migration.version

    def rollback_last(self, migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
        current = self.current_version()
        if current == 0:
            return
        migration = next((item for item in migrations if item.version == current), None)
        if migration is None:
            raise MigrationError(f"no rollback available for migration {current}")
        with self.transaction():
            migration.rollback(self.connection)
            self.connection.execute("DELETE FROM schema_migrations WHERE version = ?", (current,))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
