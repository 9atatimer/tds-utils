"""The daemon's composition root (DYNOMARK.DESIGN.md, Module map: "the
daemon's main loads Config and wires the transport, store, model and
content adapters").

The only module that names concrete adapters (``build_ports``). ``Daemon``
wires a set of ``Ports`` -- real or faked -- to the socket server and the
job loop, and binds nothing until it starts.

Threads: the asyncio loop serves the socket (every request answered there);
the job loop runs on its own thread and asks the server to deliver events
when jobs moved. The store adapter is safe to share between them.
"""

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import structlog

from dynomark_daemon.adapters.dispatch import Dispatcher
from dynomark_daemon.adapters.fetch import FetchContentSource
from dynomark_daemon.adapters.ollama import (
    OllamaClient,
    OllamaCompletion,
    OllamaEmbedding,
)
from dynomark_daemon.adapters.socket_server import Sessions, SocketServer
from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.app.hello import owned_roots_for
from dynomark_daemon.app.loop import Schedule, due_jobs
from dynomark_daemon.app.run import run_job
from dynomark_daemon.app.writer import writer_conflict
from dynomark_daemon.domain.config import Config
from dynomark_daemon.domain.connection import served_role
from dynomark_daemon.domain.job import Job
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.ports.content import ContentSourcePort
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.store import CorpusStorePort
from dynomark_daemon.settings import Settings

# --- Constants ---

log = structlog.get_logger("dynomark.daemon")

IDLE_WAIT_S: Final = 60.0
"""The longest the job loop sleeps with nothing due and nothing waking it."""
JOIN_TIMEOUT_S: Final = 10.0


# --- Clock and ids ---


class SystemClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


class RandomIds:
    """UUID4 ids: unique in the store, never reused, safe from any thread."""

    def new_id(self, kind: str) -> str:
        return f"{kind}-{uuid.uuid4().hex}"


# --- Ports ---


@dataclass(frozen=True, slots=True)
class Ports:
    """Everything the use cases reach the world through."""

    store: CorpusStorePort
    embedding: EmbeddingPort
    completion: CompletionPort
    content: ContentSourcePort
    clock: Clock
    ids: IdSource


def build_ports(settings: Settings) -> Ports:
    """The production adapters: SQLite, Ollama, fetch, the system clock."""
    client = OllamaClient(settings.ollama_url, timeout_s=settings.model_timeout_s)
    config = settings.config
    return Ports(
        store=SqliteCorpusStore.open(Path(config.store_path)),
        embedding=OllamaEmbedding(
            client, name=settings.embedding_name, model=config.embedding_model
        ),
        completion=OllamaCompletion(
            client, name=settings.completion_name, model=config.completion_model
        ),
        content=FetchContentSource(
            timeout_s=settings.capture.fetch_timeout_s,
            max_bytes=settings.capture.max_bytes,
        ),
        clock=SystemClock(),
        ids=RandomIds(),
    )


# --- The job loop ---


def _nothing() -> None:
    return None


class JobLoop:
    """Runs every due job, then waits for a wake-up or the next retry."""

    def __init__(
        self,
        config: Config,
        ports: Ports,
        *,
        on_progress: Callable[[], None] = _nothing,
    ) -> None:
        self._config = config
        self._ports = ports
        self._on_progress = on_progress
        self._wake = threading.Event()

    def wake(self) -> None:
        """Run the due jobs soon (an ingest, a retry, a snapshot arrived)."""
        self._wake.set()

    def _run(self, job: Job) -> None:
        ports, config = self._ports, self._config
        role = served_role(config.role, ports.store.writer_profile(), job.profile_id)
        roots = owned_roots_for(job.profile_id, config, store=ports.store)
        after = run_job(
            job,
            role,
            roots,
            config.retry,
            store=ports.store,
            content=ports.content,
            embedding=ports.embedding,
            completion=ports.completion,
            clock=ports.clock,
            ids=ports.ids,
            conflict=writer_conflict(role, config.host_id, roots, store=ports.store),
        )
        if after != job:
            log.info(
                "job.ran",
                job_id=job.job_id,
                before=job.state.value,
                after=after.state.value,
                attempts=after.attempts,
                last_error=after.last_error,
            )

    def run_once(self) -> Schedule:
        """Run every job due now; tell the server when any ran."""
        schedule = due_jobs(
            self._config.retry, self._ports.clock.now_ms(), store=self._ports.store
        )
        for job in schedule.due:
            try:
                self._run(job)
            except Exception:
                # One job's unexpected failure must not stop the others; it
                # is logged with its trace and the job is tried again later.
                log.exception("job.crashed", job_id=job.job_id)
        if schedule.due:
            self._on_progress()
        return schedule

    def run(self, stop: threading.Event) -> None:
        """Loop until ``stop`` is set (``wake`` makes it look at once)."""
        while not stop.is_set():
            self._wake.clear()
            schedule = self.run_once()
            now = self._ports.clock.now_ms()
            wait = IDLE_WAIT_S
            if schedule.next_retry_at is not None:
                wait = min(wait, max(0.0, (schedule.next_retry_at - now) / 1000))
            self._wake.wait(wait)


# --- The daemon ---


class Daemon:
    def __init__(self, settings: Settings, ports: Ports) -> None:
        self._settings = settings
        self._sessions = Sessions()
        self._jobs = JobLoop(settings.config, ports, on_progress=self._notify)
        dispatcher = Dispatcher(
            settings.config,
            store=ports.store,
            embedding=ports.embedding,
            completion=ports.completion,
            clock=ports.clock,
            ids=ports.ids,
            transport=self._sessions,
            wake=self._jobs.wake,
        )
        self._server = SocketServer(
            settings.socket_path, dispatcher=dispatcher, sessions=self._sessions
        )
        self._stop_jobs = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def socket_path(self) -> Path:
        return self._server.path

    def _notify(self) -> None:
        self._server.notify()

    async def start(self) -> None:
        """Listen on the socket, then start the job loop.

        Raises:
            SocketUnavailable: the socket is served, not a socket, or refused.
        """
        await self._server.start()
        self._thread = threading.Thread(
            target=self._jobs.run,
            args=(self._stop_jobs,),
            name="dynomark-jobs",
            daemon=True,
        )
        self._thread.start()
        config = self._settings.config
        log.info(
            "daemon.started",
            host_id=config.host_id,
            role=config.role.value,
            store=str(config.store_path),
            socket=str(self._server.path),
        )

    async def close(self) -> None:
        """Stop the job loop and the server."""
        self._stop_jobs.set()
        self._jobs.wake()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, JOIN_TIMEOUT_S)
        await self._server.close()
        log.info("daemon.stopped")

    async def run_until(self, stop: asyncio.Event) -> None:
        """Serve until ``stop`` is set, then close."""
        try:
            await stop.wait()
        finally:
            await self.close()
