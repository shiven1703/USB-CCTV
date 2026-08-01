"""Portable session manifest model stored beside authoritative media."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from usb_cctv_recorder.domain.states import SessionState
from usb_cctv_recorder.domain.value_objects import SessionId, UtcTimestamp
from usb_cctv_recorder.infrastructure.storage.atomic_files import AtomicPublisher

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ManifestSegment:
    """Verification facts for a finalized segment, stored beside the evidence."""

    segment_id: str
    filename: str
    duration_seconds: float
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "filename": self.filename,
            "duration_seconds": self.duration_seconds,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> ManifestSegment:
        if not isinstance(value, dict):
            raise ValueError("manifest segment must be an object")
        return cls(
            segment_id=str(value["segment_id"]),
            filename=str(value["filename"]),
            duration_seconds=float(value["duration_seconds"]),
            sha256=str(value["sha256"]),
        )


@dataclass(frozen=True, slots=True)
class SessionManifest:
    session_id: SessionId
    state: SessionState
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    segment_ids: tuple[str, ...] = ()
    segments: tuple[ManifestSegment, ...] = ()
    stop_reason: str | None = None
    failure_reason: str | None = None
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema version: {self.schema_version}")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "session_id": str(self.session_id),
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "segment_ids": list(self.segment_ids),
            "segments": [segment.to_dict() for segment in self.segments],
            "stop_reason": self.stop_reason,
            "failure_reason": self.failure_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_json(cls, content: str) -> SessionManifest:
        try:
            data = json.loads(content)
            return cls(
                schema_version=int(data["schema_version"]),
                session_id=SessionId.parse(str(data["session_id"])),
                state=SessionState(str(data["state"])),
                created_at=UtcTimestamp.parse(str(data["created_at"])),
                updated_at=UtcTimestamp.parse(str(data["updated_at"])),
                segment_ids=tuple(str(value) for value in data.get("segment_ids", [])),
                segments=tuple(
                    ManifestSegment.from_dict(value) for value in data.get("segments", [])
                ),
                stop_reason=_optional_string(data.get("stop_reason")),
                failure_reason=_optional_string(data.get("failure_reason")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid session manifest") from error


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("manifest stop/failure reason must be a string")
    return value


class ManifestStore:
    """Publishes complete manifests atomically; partial manifests are never visible."""

    def __init__(self, publisher: AtomicPublisher | None = None) -> None:
        self._publisher = publisher or AtomicPublisher()

    def save(self, path: Path, manifest: SessionManifest) -> None:
        self._publisher.publish_bytes(path, manifest.to_json().encode("utf-8"), replace=True)

    def load(self, path: Path) -> SessionManifest:
        return SessionManifest.from_json(path.read_text(encoding="utf-8"))
