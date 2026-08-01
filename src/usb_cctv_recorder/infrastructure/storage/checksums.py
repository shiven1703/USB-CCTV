"""Streaming SHA-256 checksums for authoritative media and copies."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

DEFAULT_CHUNK_SIZE = 1024 * 1024


class Sha256Service:
    def digest_stream(self, stream: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
        if chunk_size <= 0:
            raise ValueError("chunk size must be positive")
        digest = hashlib.sha256()
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
        return digest.hexdigest()

    def digest_file(self, path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
        with path.open("rb") as stream:
            return self.digest_stream(stream, chunk_size)
