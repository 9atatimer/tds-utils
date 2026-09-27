"""The daemon's unix-socket server and its ``TransportPort`` (contract/v1
README: Framing, Endpoint; Design: Security Considerations, "the daemon's
unix socket is owner-only; no TCP port").

asyncio, one event loop: every frame read on a connection is answered by
the ``Dispatcher`` before the next is read, so a connection's answers go
out in order and an ``events.replay`` answer follows the events it
replays. The use cases stay synchronous. The job loop runs on another
thread and calls ``notify`` when jobs moved; delivery then happens on the
loop, so events are pushed from one thread only.

Endpoint: the socket's directory is created 0700 when missing, the socket
is 0600. A socket another daemon still answers on is never taken over; a
dead one is replaced; a path that is not a socket is left alone.
"""

import asyncio
import os
import socket
import stat
from pathlib import Path
from typing import Final

import structlog

from dynomark_daemon.adapters.dispatch import Dispatcher, Session
from dynomark_daemon.adapters.framing import (
    MAX_INBOUND,
    MAX_OUTBOUND,
    FrameError,
    frame,
    read_frame,
)
from dynomark_daemon.domain.events import Event
from dynomark_daemon.domain.ids import ProfileId
from dynomark_daemon.wire import messages as m
from dynomark_daemon.wire.base import CONTRACT_VERSION
from dynomark_daemon.wire.codec import encode_message
from dynomark_daemon.wire.mapping import event_to_wire

# --- Constants ---

log = structlog.get_logger("dynomark.transport")

DIR_MODE: Final = 0o700
SOCKET_MODE: Final = 0o600


class DaemonAlreadyRunning(RuntimeError):
    """The socket path is served by a live daemon, or is not a socket."""


# --- Helpers ---


def _is_live(path: Path) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(path))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def _claim(path: Path) -> None:
    """Make ``path`` bindable: a private directory, no live or foreign file.

    Raises:
        DaemonAlreadyRunning: a daemon answers there, or it is not a socket.
    """
    if not path.parent.exists():
        path.parent.mkdir(mode=DIR_MODE, parents=True)
        path.parent.chmod(DIR_MODE)
    if not path.exists() and not path.is_symlink():
        return
    if not stat.S_ISSOCK(path.lstat().st_mode):
        raise DaemonAlreadyRunning(f"{path} exists and is not a socket")
    if _is_live(path):
        raise DaemonAlreadyRunning(f"a daemon is already listening on {path}")
    path.unlink()


def _is_response(message: m.AnyMessage) -> bool:
    return hasattr(message, "re")


# --- Connections ---


class Connection:
    """One extension connection: its session and its outgoing frames."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.session = Session()
        self._writer = writer

    def send(self, message: m.AnyMessage) -> None:
        """Queue one frame; a frame over 1 MiB is never sent (an answer is
        replaced by ``error`` ``internal``, an event is dropped and logged)."""
        if self._writer.is_closing():
            return
        body = encode_message(message)
        try:
            data = frame(body, limit=MAX_OUTBOUND)
        except FrameError:
            log.error("frame.oversize", type=message.type, bytes=len(body))
            if not _is_response(message) or isinstance(message, m.Error):
                return
            data = frame(
                encode_message(
                    m.Error(
                        v=CONTRACT_VERSION,
                        type="error",
                        re=getattr(message, "re", None),
                        code="internal",
                        message="the answer does not fit one frame",
                    )
                )
            )
        self._writer.write(data)

    async def drain(self) -> None:
        await self._writer.drain()

    def close(self) -> None:
        if not self._writer.is_closing():
            self._writer.close()


class Sessions:
    """The ``TransportPort``: each profile's current connection."""

    def __init__(self) -> None:
        self._by_profile: dict[ProfileId, Connection] = {}

    def register(self, connection: Connection) -> Connection | None:
        """Make ``connection`` its profile's; the one it supersedes, if any."""
        profile = connection.session.profile_id
        if profile is None:
            return None
        previous = self._by_profile.get(profile)
        self._by_profile[profile] = connection
        return previous if previous is not connection else None

    def unregister(self, connection: Connection) -> None:
        profile = connection.session.profile_id
        if profile is not None and self._by_profile.get(profile) is connection:
            del self._by_profile[profile]

    def connections(self) -> list[Connection]:
        return list(self._by_profile.values())

    def push(self, profile_id: ProfileId, event: Event) -> None:
        connection = self._by_profile.get(profile_id)
        if connection is not None:
            connection.send(event_to_wire(event))


# --- The server ---


class SocketServer:
    def __init__(
        self, path: Path, *, dispatcher: Dispatcher, sessions: Sessions
    ) -> None:
        self._path = path
        self._dispatcher = dispatcher
        self._sessions = sessions
        self._server: asyncio.Server | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._open: set[Connection] = set()

    @property
    def path(self) -> Path:
        return self._path

    async def start(self) -> None:
        """Bind and listen.

        Raises:
            DaemonAlreadyRunning: the path is served or is not a socket.
        """
        self._loop = asyncio.get_running_loop()
        _claim(self._path)
        self._server = await asyncio.start_unix_server(
            self._serve_connection, path=str(self._path)
        )
        os.chmod(self._path, SOCKET_MODE)
        log.info("server.listening", socket=str(self._path))

    async def close(self) -> None:
        """Stop listening, close every connection, remove the socket."""
        if self._server is None:
            return
        self._server.close()
        for connection in list(self._open):
            connection.close()
        await self._server.wait_closed()
        self._server = None
        if self._path.exists() and stat.S_ISSOCK(self._path.lstat().st_mode):
            self._path.unlink()
        log.info("server.closed", socket=str(self._path))

    def notify(self) -> None:
        """Deliver pending events to every connection; safe from any thread."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._deliver_all)

    def _deliver_all(self) -> None:
        for connection in self._sessions.connections():
            self._dispatcher.deliver(connection.session)

    def _supersede(self, connection: Connection) -> None:
        previous = self._sessions.register(connection)
        if previous is None:
            return
        previous.send(
            m.Error(
                v=CONTRACT_VERSION,
                type="error",
                re=None,
                code="superseded",
                message="a newer connection of this profile replaced this one",
            )
        )
        previous.close()

    async def _serve_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        connection = Connection(writer)
        self._open.add(connection)
        try:
            await self._converse(reader, connection)
        except ConnectionError as error:
            log.info("connection.lost", detail=str(error))
        finally:
            self._sessions.unregister(connection)
            self._open.discard(connection)
            connection.close()

    async def _converse(
        self, reader: asyncio.StreamReader, connection: Connection
    ) -> None:
        while True:
            try:
                body = await read_frame(reader, limit=MAX_INBOUND)
            except FrameError as error:
                log.warning("frame.refused", detail=str(error))
                return
            if body is None:
                return
            outcome = self._dispatcher.handle(body, connection.session)
            if outcome.reply is None:
                return
            connection.send(outcome.reply)
            if outcome.register:
                self._supersede(connection)
            if outcome.deliver:
                self._dispatcher.deliver(connection.session)
            await connection.drain()
