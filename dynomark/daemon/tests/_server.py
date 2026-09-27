"""Run a SocketServer on its own event-loop thread for integration tests."""

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from dynomark_daemon.adapters.dispatch import Dispatcher
from dynomark_daemon.adapters.socket_server import Sessions, SocketServer
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.ports.store import CorpusStorePort
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_config

START_TIMEOUT_S = 5.0


def build_server(
    path: Path,
    *,
    role: HostRole = HostRole.WRITER,
    store: CorpusStorePort | None = None,
) -> SocketServer:
    sessions = Sessions()
    dispatcher = Dispatcher(
        make_config(role=role),
        store=store or InMemoryCorpusStore(),
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(),
        clock=FakeClock(start_ms=1_000),
        ids=SequentialIds(),
        transport=sessions,
    )
    return SocketServer(path, dispatcher=dispatcher, sessions=sessions)


@contextmanager
def running(server: SocketServer) -> Iterator[SocketServer]:
    """The server listening on a background loop until the block ends."""
    loop = asyncio.new_event_loop()
    started = threading.Event()
    failure: list[BaseException] = []

    def run() -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.start())
        except BaseException as error:  # handed to the test thread, re-raised
            failure.append(error)
            started.set()
            return
        started.set()
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(START_TIMEOUT_S), "server did not start"
    if failure:
        thread.join(START_TIMEOUT_S)
        loop.close()
        raise failure[0]
    try:
        yield server
    finally:
        asyncio.run_coroutine_threadsafe(server.close(), loop).result(START_TIMEOUT_S)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(START_TIMEOUT_S)
        loop.close()
