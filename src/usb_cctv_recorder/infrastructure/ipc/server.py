"""Current-user Unix socket server with conservative stale-path handling."""

from __future__ import annotations

import errno
import logging
import os
import socket
import stat
import struct
from collections.abc import Callable
from pathlib import Path

from .protocol import MAXIMUM_MESSAGE_BYTES, ProtocolError, Request, Response, decode, encode

LOGGER = logging.getLogger(__name__)


class SocketLifecycleError(RuntimeError):
    """The configured socket location is unsafe or already in use."""


class UnixSocketServer:
    """One-request connections avoid shared client state in the worker loop."""

    def __init__(
        self, path: Path, handler: Callable[[Request], Response], *, user_id: int | None = None
    ) -> None:
        self._path = path
        self._handler = handler
        self._user_id = os.getuid() if user_id is None else user_id
        self._socket: socket.socket | None = None

    @property
    def path(self) -> Path:
        return self._path

    def start(self) -> None:
        self._prepare_parent()
        self._remove_stale_socket()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(os.fspath(self._path))
            os.chmod(self._path, 0o600)
            listener.listen(8)
            listener.settimeout(0.1)
        except Exception:
            listener.close()
            raise
        self._socket = listener
        LOGGER.info("ipc listening protocol_version=1 socket=%s", self._path)

    def serve_once(self) -> bool:
        listener = self._require_socket()
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            return False
        with connection:
            connection.settimeout(1)
            if not self._peer_is_current_user(connection):
                LOGGER.warning("ipc rejected peer uid")
                return True
            try:
                request = _receive_request(connection)
                response = self._handler(request)
                connection.sendall(encode(response))
            except (OSError, ProtocolError) as error:
                LOGGER.warning("ipc request rejected: %s", error)
            except Exception:
                LOGGER.exception("ipc handler failed")
        return True

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        try:
            if self._path.exists() or self._path.is_socket():
                self._path.unlink()
        except FileNotFoundError:
            pass

    def _prepare_parent(self) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_status = self._path.parent.stat()
        if not stat.S_ISDIR(parent_status.st_mode) or parent_status.st_uid != self._user_id:
            raise SocketLifecycleError("runtime directory is not owned by the current user")
        if stat.S_IMODE(parent_status.st_mode) & 0o077:
            raise SocketLifecycleError("runtime directory is not private")
        self._path.parent.chmod(0o700)

    def _remove_stale_socket(self) -> None:
        try:
            path_status = self._path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(path_status.st_mode) or path_status.st_uid != self._user_id:
            raise SocketLifecycleError("existing socket path is unsafe")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.1)
            probe.connect(os.fspath(self._path))
        except OSError as error:
            if error.errno not in {errno.ECONNREFUSED, errno.ENOENT}:
                raise SocketLifecycleError(
                    "existing socket path could not be verified stale"
                ) from error
        else:
            raise SocketLifecycleError("worker socket is already active")
        finally:
            probe.close()
        self._path.unlink()
        LOGGER.info("removed stale ipc socket=%s", self._path)

    def _peer_is_current_user(self, connection: socket.socket) -> bool:
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        _, uid, _ = _CREDENTIALS.unpack(credentials)
        return uid == self._user_id

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise SocketLifecycleError("IPC server is not running")
        return self._socket


_CREDENTIALS = struct.Struct("3i")


def _receive_request(connection: socket.socket) -> Request:
    header = _receive_exact(connection, 4)
    length = int.from_bytes(header, "big")
    if length > MAXIMUM_MESSAGE_BYTES:
        raise ProtocolError("message exceeds maximum size")
    decoded = decode(header + _receive_exact(connection, length))
    if not isinstance(decoded, Request):
        raise ProtocolError("client must send a request")
    return decoded


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        received = connection.recv(size - len(chunks))
        if not received:
            raise ProtocolError("truncated IPC frame")
        chunks.extend(received)
    return bytes(chunks)
