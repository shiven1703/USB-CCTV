"""Shared durable publication helpers for evidence-affecting files."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from .checksums import Sha256Service


class AtomicPublishError(RuntimeError):
    """A publication did not reach its final atomically visible name."""


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class AtomicPublisher:
    """Publishes a new file only after its temporary sibling is durable."""

    def publish_bytes(self, destination: Path, content: bytes, *, replace: bool = False) -> None:
        self.publish(destination, lambda stream: stream.write(content), replace=replace)

    def publish(
        self,
        destination: Path,
        write_content: Callable[[BinaryIO], int | None],
        *,
        replace: bool = False,
    ) -> None:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.exists() and not replace:
            raise AtomicPublishError(f"refusing to overwrite existing evidence file: {destination}")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                write_content(stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            _fsync_directory(destination.parent)
        except BaseException as error:
            temporary.unlink(missing_ok=True)
            raise AtomicPublishError(f"atomic publication failed for {destination}") from error


class CrossFilesystemCopier:
    """Copy, fsync, checksum-verify, then atomically publish at the destination.

    The source is intentionally retained. A later catalogue transaction may delete it only
    after its own commit, so this helper cannot accidentally lose authoritative evidence.
    """

    def __init__(self, checksums: Sha256Service | None = None) -> None:
        self._checksums = checksums or Sha256Service()

    def copy_and_verify(
        self, source: Path, destination: Path, chunk_size: int = 1024 * 1024
    ) -> str:
        if not source.is_file():
            raise FileNotFoundError(source)
        if destination.exists():
            raise AtomicPublishError(f"refusing to overwrite existing evidence file: {destination}")
        if chunk_size <= 0:
            raise ValueError("chunk size must be positive")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            source_digest = self._checksums.digest_file(source, chunk_size)
            with source.open("rb") as input_stream, os.fdopen(descriptor, "wb") as output_stream:
                while chunk := input_stream.read(chunk_size):
                    output_stream.write(chunk)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            if source.stat().st_size != temporary.stat().st_size:
                raise AtomicPublishError("copied byte count does not match source")
            if self._checksums.digest_file(temporary, chunk_size) != source_digest:
                raise AtomicPublishError("copied checksum does not match source")
            os.replace(temporary, destination)
            _fsync_directory(destination.parent)
            return source_digest
        except BaseException as error:
            temporary.unlink(missing_ok=True)
            if isinstance(error, AtomicPublishError):
                raise
            raise AtomicPublishError(f"cross-filesystem copy failed for {destination}") from error
