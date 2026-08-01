"""Durable append-only JSONL journal for session evidence events."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from usb_cctv_recorder.domain.value_objects import UtcTimestamp


@dataclass(frozen=True, slots=True)
class JournalEvent:
    event_type: str
    occurred_at: UtcTimestamp
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if not self.event_type:
            raise ValueError("event type is required")

    def to_json_line(self) -> bytes:
        data = {
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
        }
        return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    @classmethod
    def from_json_line(cls, line: str) -> JournalEvent:
        try:
            data: dict[str, Any] = json.loads(line)
            payload = data["payload"]
            if not isinstance(payload, dict):
                raise ValueError("event payload must be an object")
            return cls(
                event_type=str(data["event_type"]),
                occurred_at=UtcTimestamp.parse(str(data["occurred_at"])),
                payload=payload,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("invalid event journal line") from error


class JsonlEventJournal:
    """Append events with O_APPEND and fsync; it deliberately has no rewrite API."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: JournalEvent) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            data = event.to_json_line()
            written = 0
            while written < len(data):
                written += os.write(descriptor, data[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def read_all(self) -> tuple[JournalEvent, ...]:
        if not self.path.exists():
            return ()
        return tuple(
            JournalEvent.from_json_line(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line
        )
