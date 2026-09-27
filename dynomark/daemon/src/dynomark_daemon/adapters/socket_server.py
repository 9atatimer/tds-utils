"""The daemon's unix-socket server and its ``TransportPort`` (contract/v1
README: Framing, Endpoint; Design: Security Considerations, "the daemon's
unix socket is owner-only; no TCP port").

asyncio, one event loop that only moves bytes: no use case, store read or
model call runs on it, so no connection waits on another's work.

- The lane: one worker thread runs the ``Dispatcher`` for every frame and
  every event delivery, in arrival order. A connection's next frame is read
  only after its previous one was answered, so its answers go out in order
  and an ``events.replay`` answer follows the events it replays.
- The model pool: a request that waits on a model (``MODEL_REQUESTS``:
  ``ask``, ``search``, ``diff.propose``) is admitted on the lane, then runs
  on a pool thread while the connection's later frames are served; its
  answer goes out when it is ready (contract v1: responses may arrive in any
  order).

The job loop runs on its own thread and calls ``notify`` when jobs moved;
delivery then runs on the lane. Frames are written on the loop only: a
``Connection.send`` from a worker thread is handed to the loop.

Endpoint: the socket's directory is created 0700 when missing, the socket
is 0600. A socket another daemon still answers on is never taken over; a
dead one is replaced; a path that is not a socket is left alone.
"""

import asyncio
import os
import socket
import stat
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Final, TypeVar

import structlog

from dynomark_daemon.adapters.dispatch import Dispatcher, Outcome, Session
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
MODEL_THREADS: Final = 4
"""Model-backed requests answered at once; more wait for a free thread."""

T = TypeVar("T")


class SocketUnavailable(RuntimeError):
    """The daemon cannot listen on its socket path."""


class DaemonAlreadyRunning(SocketUnavailable):
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

    def __init__(
        self, writer: asyncio.StreamWriter, loop: asyncio.AbstractEventLoop
    ) -> None:
        self.session = Session()
        self._writer = writer
        self._loop = loop
        self._loop_thread = threading.get_ident()

    def send(self, message: m.AnyMessage) -> None:
        """Queue one frame, from any thread (it is written on the loop); a
        frame over 1 MiB is never sent (an answer is replaced by ``error``
        ``internal``, an event is dropped and logged)."""
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
        if threading.get_ident() == self._loop_thread:
            self._write(data)
        elif not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._write, data)

    def _write(self, data: bytes) -> None:
        if not self._writer.is_closing():
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
        self._lane: ThreadPoolExecutor | None = None
        self._models: ThreadPoolExecutor | None = None
        self._answering: set[asyncio.Task[None]] = set()

    @property
    def path(self) -> Path:
        return self._path

    async def start(self) -> None:
        """Bind and listen.

        Raises:
            DaemonAlreadyRunning: the path is served or is not a socket.
            SocketUnavailable: the OS refuses the path (too long, no access).
        """
        self._loop = asyncio.get_running_loop()
        self._lane = ThreadPoolExecutor(1, thread_name_prefix="dynomark-lane")
        self._models = ThreadPoolExecutor(
            MODEL_THREADS, thread_name_prefix="dynomark-models"
        )
        try:
            _claim(self._path)
            self._server = await asyncio.start_unix_server(
                self._serve_connection, path=str(self._path)
            )
        except OSError as error:
            why = f"cannot listen on {self._path}: {error}"
            raise SocketUnavailable(why) from error
        os.chmod(self._path, SOCKET_MODE)
        log.info("server.listening", socket=str(self._path))

    async def close(self) -> None:
        """Stop listening, close every connection, remove the socket."""
        if self._server is None:
            return
        self._server.close()
        for connection in list(self._open):
            connection.close()
        for task in list(self._answering):
            task.cancel()
        await self._server.wait_closed()
        self._server = None
        if self._models is not None:
            self._models.shutdown(wait=False, cancel_futures=True)
        if self._lane is not None:
            await asyncio.to_thread(self._lane.shutdown, wait=True)
        if self._path.exists() and stat.S_ISSOCK(self._path.lstat().st_mode):
            self._path.unlink()
        log.info("server.closed", socket=str(self._path))

    def notify(self) -> None:
        """Deliver pending events to every connection; safe from any thread."""
        if self._lane is None:
            return
        try:
            self._lane.submit(self._deliver_all)
        except RuntimeError:
            return  # shutting down: the next connection replays them

    async def _on(self, pool: ThreadPoolExecutor | None, work: Callable[[], T]) -> T:
        """Run ``work`` on ``pool`` (the lane or the model pool), off the loop."""
        if pool is None or self._loop is None:
            raise RuntimeError("the server is not started")
        return await self._loop.run_in_executor(pool, work)

    def _deliver_all(self) -> None:
        for connection in self._sessions.connections():
            try:
                self._dispatcher.deliver(connection.session)
            except Exception:
                # Submitted from the job thread, nobody awaits this: log with
                # the trace, and the connection's next replay re-sends.
                log.exception("events.deliver_failed")

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
        connection = Connection(writer, asyncio.get_running_loop())
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
            outcome = await self._on(
                self._lane,
                partial(
                    self._dispatcher.handle,
                    body,
                    connection.session,
                    defer_models=True,
                ),
            )
            if outcome.deferred is not None:
                task = asyncio.create_task(self._answer_later(connection, outcome))
                self._answering.add(task)
                task.add_done_callback(self._answering.discard)
                continue
            if not await self._reply(connection, outcome):
                return

    async def _answer_later(self, connection: Connection, admitted: Outcome) -> None:
        """Run an admitted model-backed request on the model pool and send its
        answer when it is ready."""
        if admitted.deferred is None:
            return
        try:
            outcome = await self._on(self._models, admitted.deferred)
            await self._reply(connection, outcome)
        except ConnectionError as error:
            log.info("connection.lost", detail=str(error))

    async def _reply(self, connection: Connection, outcome: Outcome) -> bool:
        """Send ``outcome``; whether the connection stays open."""
        if outcome.reply is None:
            return False
        connection.send(outcome.reply)
        if outcome.register:
            self._supersede(connection)
        if outcome.deliver:
            await self._on(
                self._lane, partial(self._dispatcher.deliver, connection.session)
            )
        await connection.drain()
        return True
