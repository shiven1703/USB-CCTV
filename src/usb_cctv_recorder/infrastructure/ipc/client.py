"""Blocking local IPC client; presentation invokes it off the Qt event loop."""

from __future__ import annotations

import os
import socket
from pathlib import Path

from .protocol import MAXIMUM_MESSAGE_BYTES, ProtocolError, Request, Response, decode, encode


class UnixSocketClient:
    def __init__(self, path: Path, timeout_seconds: float = 2) -> None:
        self._path = path
        self._timeout_seconds = timeout_seconds

    def request(self, request: Request) -> Response:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self._timeout_seconds)
            connection.connect(os.fspath(self._path))
            connection.sendall(encode(request))
            header = _receive_exact(connection, 4)
            length = int.from_bytes(header, "big")
            if length > MAXIMUM_MESSAGE_BYTES:
                raise ProtocolError("message exceeds maximum size")
            response = decode(header + _receive_exact(connection, length))
        if not isinstance(response, Response):
            raise ProtocolError("worker returned a request")
        return response


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        received = connection.recv(size - len(chunks))
        if not received:
            raise ProtocolError("truncated IPC frame")
        chunks.extend(received)
    return bytes(chunks)
