"""Small, versioned IPC schema for the local recorder worker."""

from __future__ import annotations

import json
import struct
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

PROTOCOL_VERSION = 1
MAXIMUM_MESSAGE_BYTES = 16 * 1024
_HEADER = struct.Struct("!I")


class ProtocolError(ValueError):
    """A peer sent a frame outside the deliberately closed protocol."""


class Command(StrEnum):
    STATUS = "status"
    START = "start"
    STOP = "stop"
    RETRY = "retry"
    FORCE_STOP = "force_stop"


@dataclass(frozen=True, slots=True)
class Request:
    command: Command
    command_id: str

    @classmethod
    def parse(cls, value: object) -> Request:
        fields = _object(value, "request")
        _exact_keys(fields, {"protocol_version", "command", "command_id"}, "request")
        _version(fields)
        try:
            command = Command(_string(fields["command"], "command"))
        except ValueError as error:
            raise ProtocolError("unknown command") from error
        command_id = _string(fields["command_id"], "command_id")
        _canonical_command_id(command_id)
        return cls(command, command_id)

    def to_mapping(self) -> dict[str, object]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "command": self.command.value,
            "command_id": self.command_id,
        }


@dataclass(frozen=True, slots=True)
class Response:
    command: Command
    command_id: str
    state: str
    accepted: bool
    error_code: str | None = None
    session_id: str | None = None

    @classmethod
    def parse(cls, value: object) -> Response:
        fields = _object(value, "response")
        _exact_keys(
            fields,
            {
                "protocol_version",
                "command",
                "command_id",
                "state",
                "accepted",
                "error_code",
                "session_id",
            },
            "response",
        )
        _version(fields)
        try:
            command = Command(_string(fields["command"], "command"))
        except ValueError as error:
            raise ProtocolError("unknown response command") from error
        command_id = _string(fields["command_id"], "command_id")
        _canonical_command_id(command_id)
        _string(fields["state"], "state")
        if not isinstance(fields["accepted"], bool):
            raise ProtocolError("accepted must be a boolean")
        for name in ("error_code", "session_id"):
            if fields[name] is not None:
                _string(fields[name], name)
        return cls(
            command,
            command_id,
            fields["state"],
            fields["accepted"],
            fields["error_code"],
            fields["session_id"],
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "command": self.command.value,
            "command_id": self.command_id,
            "state": self.state,
            "accepted": self.accepted,
            "error_code": self.error_code,
            "session_id": self.session_id,
        }


def encode(value: Request | Response) -> bytes:
    """Serialize one bounded JSON frame; no streaming or arbitrary payloads exist."""
    payload = json.dumps(value.to_mapping(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(payload) > MAXIMUM_MESSAGE_BYTES:
        raise ProtocolError("message exceeds maximum size")
    return _HEADER.pack(len(payload)) + payload


def decode(frame: bytes) -> Request | Response:
    """Decode one complete frame for tests and clients with an in-memory transport."""
    if len(frame) < _HEADER.size:
        raise ProtocolError("frame is missing its length header")
    length = _HEADER.unpack(frame[: _HEADER.size])[0]
    if length > MAXIMUM_MESSAGE_BYTES:
        raise ProtocolError("message exceeds maximum size")
    if len(frame) != _HEADER.size + length:
        raise ProtocolError("frame length does not match payload")
    try:
        value = json.loads(frame[_HEADER.size :].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("message is not valid UTF-8 JSON") from error
    fields = _object(value, "message")
    if "accepted" in fields:
        return Response.parse(fields)
    return Request.parse(fields)


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProtocolError(f"{name} must be a JSON object")
    return value


def _exact_keys(fields: dict[str, Any], expected: set[str], name: str) -> None:
    if set(fields) != expected:
        raise ProtocolError(f"{name} fields are invalid")


def _version(fields: dict[str, Any]) -> None:
    if fields.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol_version")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{name} must be a non-empty string")
    return value


def _canonical_command_id(value: str) -> None:
    try:
        parsed_id = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ProtocolError("command_id must be a UUID") from error
    if str(parsed_id) != value:
        raise ProtocolError("command_id must be a canonical UUID")
