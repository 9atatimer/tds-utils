"""The transport adapter's request side: one frame body in, one answer out.

contract/v1/README.md, Connection lifecycle step 3: a body that is not a
JSON object closes the connection (no answer); then ``hello_required``,
then ``version_mismatch`` (another ``v``, or a request outside the
connection's mode), then the schema (``invalid``). A request that passes
is served by its use case and answered by exactly one frame: its result or
an ``error`` of the closed code set. Nothing here is a rule of the design;
it maps wire values to use cases and back.

Events: use cases record them in the store; ``deliver`` pushes them through
the session's own ``TransportPort`` (its connection, never a newer one of the
profile).
A connection gets a ``batch.offer`` only once a ``tree.snapshot`` was
recorded on it, and then every unacknowledged event is re-sent once.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Final, TypeVar, cast

import structlog

from dynomark_daemon.adapters.framing import MAX_OUTBOUND
from dynomark_daemon.app.ask import ask
from dynomark_daemon.app.diffs import (
    accept_diff,
    diff_items_page,
    list_diffs_page,
    request_diff,
)
from dynomark_daemon.app.errors import (
    Busy,
    InvalidRequest,
    TreeNotReady,
    UnknownRecord,
)
from dynomark_daemon.app.events import (
    ack_events,
    deliver,
    fail_oversize_offers,
    replay_events,
)
from dynomark_daemon.app.explain import explain_placement
from dynomark_daemon.app.feedback import record_feedback
from dynomark_daemon.app.flags import set_folder_flags
from dynomark_daemon.app.hello import hello, status
from dynomark_daemon.app.index import local_index_page
from dynomark_daemon.app.ingest import ingest
from dynomark_daemon.app.jobs import list_batches_page, list_jobs_page, retry_job
from dynomark_daemon.app.pages import Page, StaleCursor, offset_page
from dynomark_daemon.app.receipt import receive_receipt
from dynomark_daemon.app.run import current_outline
from dynomark_daemon.app.search import search_page
from dynomark_daemon.app.tree import record_tree_snapshot
from dynomark_daemon.app.undo import undo
from dynomark_daemon.app.writer import (
    ensure_writer_marker,
    writer_conflict,
    writer_status,
)
from dynomark_daemon.domain.bookmark import Capture, Identity
from dynomark_daemon.domain.chat import Question
from dynomark_daemon.domain.config import Config
from dynomark_daemon.domain.connection import HelloMode
from dynomark_daemon.domain.diff import DiffKind
from dynomark_daemon.domain.ids import (
    BatchId,
    DiffId,
    EventId,
    ItemId,
    JobId,
    NodeId,
    ProfileId,
    RequestId,
)
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.search import Query
from dynomark_daemon.domain.tree import OwnedRoots
from dynomark_daemon.domain.writer import WriterConflict
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.errors import PortError
from dynomark_daemon.ports.store import CorpusStorePort
from dynomark_daemon.ports.transport import TransportPort
from dynomark_daemon.wire import messages as m
from dynomark_daemon.wire import values as w
from dynomark_daemon.wire.admission import REQUESTS, refusal
from dynomark_daemon.wire.base import CONTRACT_VERSION
from dynomark_daemon.wire.codec import (
    InvalidMessage,
    MalformedBody,
    decode_body,
    encode_message,
    peek_envelope,
)
from dynomark_daemon.wire.mapping import (
    answer_to_wire,
    batch_summary_to_wire,
    bookmark_from_wire,
    capture_from_wire,
    corpus_hit_to_wire,
    diff_item_to_wire,
    folder_path_from_wire,
    job_to_wire,
    local_index_row_to_wire,
    model_info_to_wire,
    move_from_wire,
    outline_folder_to_wire,
    owned_roots_to_wire,
    placement_to_wire,
    receipt_from_wire,
    snapshot_from_wire,
    tree_diff_to_wire,
    turn_from_wire,
    undo_drop_to_wire,
)
from dynomark_daemon.wire.messages import MESSAGE_MODELS

T = TypeVar("T")

# --- Constants ---

log = structlog.get_logger("dynomark.transport")

V: Final = CONTRACT_VERSION
MAX_DETAIL: Final = 4096
MODEL_REQUESTS: Final = frozenset({"ask", "search", "diff.propose"})
"""Requests whose answer waits on a model call. They change no connection
state and nothing a later request on the connection depends on, so the
transport may answer them concurrently with everything else (contract v1:
responses may arrive in any order)."""


# --- Connection standing ---


@dataclass
class Session:
    """One connection's standing, set by its first ``hello``. ``transport``
    reaches that connection alone: the events this standing chooses go there,
    never to a newer connection of the profile (``None``: the dispatcher's
    profile-wide transport)."""

    profile_id: ProfileId | None = None
    mode: HelloMode | None = None
    role: HostRole = HostRole.READER
    roots: OwnedRoots | None = None
    snapshot_seen: bool = False
    replay_pending: bool = False
    greeting: m.HelloResult | None = None
    """The answer to the first ``hello``; a repeat is answered with it."""
    transport: TransportPort | None = None

    def offers_ready(self, *, conflict: bool) -> bool:
        """Full mode, served writer, not in writer conflict, and a
        ``tree.snapshot`` recorded on it (markers re-read from it)."""
        return (
            self.mode is HelloMode.FULL
            and self.role is HostRole.WRITER
            and self.snapshot_seen
            and not conflict
        )


@dataclass(frozen=True, slots=True)
class Outcome:
    """The answer to one frame. ``reply`` ``None`` closes the connection --
    unless ``deferred`` is set: then the answer is ``deferred()``, a model
    call the transport runs apart from the connection's other requests;
    ``register`` makes this connection its profile's (superseding an older
    one); ``deliver`` asks for ``Dispatcher.deliver`` after the reply."""

    reply: m.AnyMessage | None
    register: bool = False
    deliver: bool = False
    deferred: "Callable[[], Outcome] | None" = None


@dataclass
class _Timing:
    """When each job's save was received, for Goal 2's log line."""

    received: dict[JobId, int] = field(default_factory=dict)


# --- Helpers ---


def _nothing() -> None:
    return None


def _error(re: str | None, code: w.ErrorCode, detail: str) -> m.Error:
    return m.Error(v=V, type="error", re=re, code=code, message=detail[:MAX_DETAIL])


def _fits(message: m.AnyMessage) -> bool:
    return len(encode_message(message)) <= MAX_OUTBOUND


def _fit_page(
    page_at: Callable[[int], Page[T]],
    render: Callable[[Sequence[T], str | None], m.AnyMessage],
    limit: int,
) -> m.AnyMessage:
    """The page answer, shortened until its frame fits 1 MiB; a single row that
    alone cannot fit is left out and the cursor moves past it."""
    while True:
        page = page_at(limit)
        reply = render(page.items, page.next_cursor)
        if _fits(reply):
            return reply
        if limit == 1:
            return render((), page.next_cursor)
        limit = max(1, limit // 2)


def _fit_explanation(reply: m.PlacementExplainResult) -> m.PlacementExplainResult:
    """Drop trailing neighbours, then feedback ids, until the frame fits."""
    reason = reply.reason
    while not _fits(reply) and (reason.neighbours or reason.feedback_ids):
        if reason.neighbours:
            reason = reason.model_copy(update={"neighbours": reason.neighbours[:-1]})
        else:
            reason = reason.model_copy(
                update={"feedback_ids": reason.feedback_ids[:-1]}
            )
        reply = reply.model_copy(update={"reason": reason})
    return reply


def _fit_answer(reply: m.AskResult) -> m.AskResult:
    """Drop trailing citations, then external urls, until the frame fits."""
    answer = reply.answer
    while not _fits(reply) and (answer.citations or answer.external_urls):
        if answer.citations:
            answer = answer.model_copy(update={"citations": answer.citations[:-1]})
        else:
            answer = answer.model_copy(
                update={"external_urls": answer.external_urls[:-1]}
            )
        reply = reply.model_copy(update={"answer": answer})
    return reply


def _refused(re: str, refusal: NotWriter | WriterConflict) -> m.Error:
    """``not_writer`` on a reader, ``writer_conflict`` on a writer that sees
    another host's marker."""
    if isinstance(refusal, NotWriter):
        return _error(re, "not_writer", f"this host is a reader ({refusal.use_case})")
    return _error(re, "writer_conflict", refusal.reason())


def _profile(session: Session) -> ProfileId:
    """The connection's profile; admission guarantees a hello came first."""
    if session.profile_id is None:
        raise InvalidRequest("no hello on this connection")
    return session.profile_id


def _roots(session: Session) -> OwnedRoots:
    if session.roots is None:
        raise InvalidRequest("no hello on this connection")
    return session.roots


# --- Handlers ---

Handler = Callable[[m.AnyMessage, Session], Outcome]
R = TypeVar("R", bound=m.AnyMessage)
_TYPE_OF: Final[dict[type[object], str]] = {
    model: name for name, model in MESSAGE_MODELS.items()
}


def _on(model: type[R], handle: Callable[[R, Session], Outcome]) -> tuple[str, Handler]:
    """``handle`` registered for ``model``'s message type."""

    def run(message: m.AnyMessage, session: Session) -> Outcome:
        if not isinstance(message, model):
            raise InvalidRequest(f"{message.type} is not a {_TYPE_OF[model]}")
        return handle(message, session)

    return _TYPE_OF[model], run


# --- The dispatcher ---


class Dispatcher:
    def __init__(
        self,
        config: Config,
        *,
        store: CorpusStorePort,
        embedding: EmbeddingPort,
        completion: CompletionPort,
        clock: Clock,
        ids: IdSource,
        transport: TransportPort,
        wake: Callable[[], None] = _nothing,
    ) -> None:
        self._config = config
        self._store = store
        self._embedding = embedding
        self._completion = completion
        self._clock = clock
        self._ids = ids
        self._transport = transport
        self._wake = wake
        self._timing = _Timing()
        self._handlers: dict[str, Handler] = dict(
            [
                _on(m.Hello, self._hello),
                _on(m.Status, self._status),
                _on(m.Ingest, self._ingest),
                _on(m.JobRetry, self._job_retry),
                _on(m.JobList, self._job_list),
                _on(m.TreeSnapshot, self._tree_snapshot),
                _on(m.MoveObserved, self._move_observed),
                _on(m.BatchReceiptMessage, self._batch_receipt),
                _on(m.BatchList, self._batch_list),
                _on(m.Undo, self._undo),
                _on(m.EventsReplay, self._events_replay),
                _on(m.EventsAck, self._events_ack),
                _on(m.IndexPull, self._index_pull),
                _on(m.Search, self._search),
                _on(m.Ask, self._ask),
                _on(m.PlacementExplain, self._placement_explain),
                _on(m.DiffPropose, self._diff_propose),
                _on(m.DiffList, self._diff_list),
                _on(m.DiffPage, self._diff_page),
                _on(m.DiffAccept, self._diff_accept),
                _on(m.OutlineGet, self._outline_get),
                _on(m.FolderFlagsSet, self._folder_flags_set),
                _on(m.WriterStatus, self._writer_status),
            ]
        )

    # --- Entry points ---

    def handle(
        self, body: bytes, session: Session, *, defer_models: bool = False
    ) -> Outcome:
        """Answer one frame body received on ``session``'s connection. With
        ``defer_models``, a request of ``MODEL_REQUESTS`` that passes
        admission is answered by the returned outcome's ``deferred``."""
        try:
            envelope = peek_envelope(body)
        except MalformedBody as error:
            log.warning("frame.malformed", detail=str(error))
            return Outcome(reply=None)
        message_type = envelope.type if isinstance(envelope.type, str) else ""
        code = refusal(message_type, envelope.v, mode=session.mode)
        if code is not None:
            return Outcome(_error(envelope.id, code, f"{message_type}: {code}"))
        try:
            message = decode_body(body)
        except MalformedBody:
            return Outcome(reply=None)
        except InvalidMessage as error:
            return Outcome(_error(error.re, "invalid", str(error)))
        if message.type not in REQUESTS:
            return Outcome(_error(None, "invalid", f"{message.type} is not a request"))
        if defer_models and message.type in MODEL_REQUESTS:
            return Outcome(reply=None, deferred=partial(self._serve, message, session))
        return self._serve(message, session)

    def deliver(self, session: Session) -> None:
        """Push the events this connection may have now: every unacknowledged
        one once after its first snapshot, else only those not pushed yet."""
        if session.profile_id is None or session.mode in (None, HelloMode.REFUSED):
            return
        mode = cast(HelloMode, session.mode)
        self._withdraw_oversize(session.profile_id)
        send = replay_events if session.replay_pending else deliver
        session.replay_pending = False
        send(
            session.profile_id,
            mode=mode,
            offers_ready=self._offers_ready(session),
            store=self._store,
            transport=self._sender(session),
        )

    def _sender(self, session: Session) -> TransportPort:
        """Where events chosen by ``session``'s standing go: its connection."""
        return session.transport or self._transport

    def _withdraw_oversize(self, profile_id: ProfileId) -> None:
        for job in fail_oversize_offers(
            profile_id,
            store=self._store,
            transport=self._transport,
            clock=self._clock,
            ids=self._ids,
        ):
            log.error("batch.oversize", job_id=job.job_id, batch_id=job.batch_id)

    # --- Writer standing ---

    def _conflict(self, session: Session) -> WriterConflict | None:
        if session.roots is None:
            return None
        return writer_conflict(
            session.role, self._config.host_id, session.roots, store=self._store
        )

    def _offers_ready(self, session: Session) -> bool:
        return session.offers_ready(conflict=self._conflict(session) is not None)

    # --- Serving ---

    def _serve(self, message: m.AnyMessage, session: Session) -> Outcome:
        request_id = getattr(message, "id", None)
        try:
            return self._route(message, session)
        except UnknownRecord as error:
            return Outcome(_error(request_id, "not_found", str(error)))
        except InvalidRequest as error:
            return Outcome(_error(request_id, "invalid", str(error)))
        except (Busy, TreeNotReady) as error:
            return Outcome(_error(request_id, "busy", str(error)))
        except StaleCursor as error:
            return Outcome(_error(request_id, "stale_cursor", str(error)))
        except PortError as error:
            # A model or embedding call failed: busy when trying again may
            # help (a model loading), else internal.
            code: w.ErrorCode = "busy" if error.retryable else "internal"
            log.warning("request.port_failed", type=message.type, detail=str(error))
            return Outcome(_error(request_id, code, str(error)))
        except Exception as error:
            # Every request is answered (contract v1, Envelope): an unexpected
            # failure is logged with its trace and answered internal, which
            # the extension retries with the same id.
            log.exception("request.failed", type=message.type, request_id=request_id)
            return Outcome(_error(request_id, "internal", type(error).__name__))

    def handled_types(self) -> frozenset[str]:
        """The request types this dispatcher has a handler for."""
        return frozenset(self._handlers)

    def _route(self, message: m.AnyMessage, session: Session) -> Outcome:
        handler = self._handlers.get(message.type)
        if handler is None:
            request_id = getattr(message, "id", None)
            detail = f"{message.type} is not a request this daemon serves"
            return Outcome(_error(request_id, "invalid", detail))
        return handler(message, session)

    # --- Connection ---

    def _hello(self, message: m.Hello, session: Session) -> Outcome:
        if session.greeting is not None:
            return Outcome(session.greeting.model_copy(update={"re": message.id}))
        greeting = hello(
            ProfileId(message.profile_id),
            message.v,
            folder_path_from_wire(message.follow_up),
            self._config,
            store=self._store,
        )
        reply = m.HelloResult(
            v=greeting.version,
            type="hello.result",
            re=message.id,
            host_id=greeting.host_id,
            role=greeting.role.value,
            mode=greeting.mode.value,
            owned_roots=owned_roots_to_wire(greeting.owned_roots),
        )
        session.greeting = reply
        session.profile_id = ProfileId(message.profile_id)
        session.mode = greeting.mode
        session.role = greeting.role
        session.roots = greeting.owned_roots
        served = greeting.mode is not HelloMode.REFUSED
        log.info(
            "connection.hello",
            profile_id=message.profile_id,
            mode=greeting.mode.value,
            role=greeting.role.value,
        )
        return Outcome(reply, register=served, deliver=served)

    def _status(self, message: m.Status, session: Session) -> Outcome:
        daemon = status(session.role, self._config, store=self._store)
        return Outcome(
            m.StatusResult(
                v=V,
                type="status.result",
                re=message.id,
                role=daemon.role.value,
                host_id=daemon.host_id,
                contract_version=daemon.contract_version,
                models=w.Models(
                    embedding=model_info_to_wire(daemon.embedding),
                    completion=model_info_to_wire(daemon.completion),
                ),
                queue_depth=daemon.queue_depth,
            )
        )

    # --- Jobs ---

    def _ingest(self, message: m.Ingest, session: Session) -> Outcome:
        profile = _profile(session)
        bookmark = bookmark_from_wire(message.bookmark)
        capture = (
            Capture.none()
            if message.capture is None
            else capture_from_wire(message.capture)
        )
        known = self._store.find_job(
            profile, bookmark.node_id, Identity.from_url(bookmark.url)
        )
        job = ingest(
            bookmark,
            capture,
            profile,
            backfill=message.backfill,
            store=self._store,
            clock=self._clock,
            ids=self._ids,
        )
        if known is None:
            self._timing.received[job.job_id] = job.updated_at
            log.info(
                "ingest.received",
                job_id=job.job_id,
                profile_id=profile,
                identity=job.identity.value,
                received_at=job.updated_at,
            )
        self._wake()
        return Outcome(
            m.IngestResult(
                v=V, type="ingest.result", re=message.id, job=job_to_wire(job)
            )
        )

    def _job_retry(self, message: m.JobRetry, session: Session) -> Outcome:
        job = retry_job(
            JobId(message.job_id),
            _profile(session),
            store=self._store,
            clock=self._clock,
            ids=self._ids,
        )
        self._wake()
        return Outcome(
            m.JobRetryResult(
                v=V, type="job.retry.result", re=message.id, job=job_to_wire(job)
            ),
            deliver=True,
        )

    def _job_list(self, message: m.JobList, session: Session) -> Outcome:
        profile = _profile(session)
        state = None if message.state is None else JobState(message.state)
        reply = _fit_page(
            lambda limit: list_jobs_page(
                profile, state, message.cursor, limit, store=self._store
            ),
            lambda jobs, cursor: m.JobListResult(
                v=V,
                type="job.list.result",
                re=message.id,
                jobs=[job_to_wire(job) for job in jobs],
                next_cursor=cursor,
            ),
            message.limit or m.LARGE_PAGE,
        )
        return Outcome(reply)

    # --- Tree, moves, batches ---

    def _tree_snapshot(self, message: m.TreeSnapshot, session: Session) -> Outcome:
        record_tree_snapshot(
            snapshot_from_wire(message.snapshot), session.role, store=self._store
        )
        ensure_writer_marker(
            session.role,
            self._config.host_id,
            _roots(session),
            _profile(session),
            store=self._store,
            clock=self._clock,
            ids=self._ids,
        )
        first = not session.snapshot_seen
        session.snapshot_seen = True
        session.replay_pending = session.replay_pending or first
        self._wake()
        return Outcome(
            m.TreeSnapshotResult(v=V, type="tree.snapshot.result", re=message.id),
            deliver=True,
        )

    def _move_observed(self, message: m.MoveObserved, session: Session) -> Outcome:
        feedback = record_feedback(
            move_from_wire(message.move),
            session.role,
            _roots(session),
            store=self._store,
        )
        log.info(
            "move.observed",
            node_id=message.move.node_id,
            origin=message.move.origin,
            feedback=feedback is not None,
        )
        return Outcome(
            m.MoveObservedResult(v=V, type="move.observed.result", re=message.id)
        )

    def _batch_receipt(
        self, message: m.BatchReceiptMessage, session: Session
    ) -> Outcome:
        recorded = receive_receipt(
            receipt_from_wire(message.receipt),
            _roots(session),
            store=self._store,
            clock=self._clock,
            ids=self._ids,
        )
        job = recorded.job
        if recorded.first and job is not None and job.state is JobState.FILED:
            applied_at = self._clock.now_ms()
            received_at = self._timing.received.pop(job.job_id, None)
            log.info(
                "job.applied",
                job_id=job.job_id,
                batch_id=message.receipt.batch_id,
                received_at=received_at,
                applied_at=applied_at,
                interval_ms=None if received_at is None else applied_at - received_at,
            )
        return Outcome(
            m.BatchReceiptMessageResult(
                v=V, type="batch.receipt.result", re=message.id
            ),
            deliver=True,
        )

    def _batch_list(self, message: m.BatchList, session: Session) -> Outcome:
        profile = _profile(session)
        reply = _fit_page(
            lambda limit: list_batches_page(
                profile, message.cursor, limit, store=self._store
            ),
            lambda batches, cursor: m.BatchListResult(
                v=V,
                type="batch.list.result",
                re=message.id,
                batches=[batch_summary_to_wire(record) for record in batches],
                next_cursor=cursor,
            ),
            message.limit or m.SMALL_PAGE,
        )
        return Outcome(reply)

    def _undo(self, message: m.Undo, session: Session) -> Outcome:
        result = undo(
            BatchId(message.batch_id),
            session.role,
            _roots(session),
            conflict=self._conflict(session),
            store=self._store,
            clock=self._clock,
            ids=self._ids,
        )
        if isinstance(result, NotWriter | WriterConflict):
            return Outcome(_refused(message.id, result))
        return Outcome(
            m.UndoResult(
                v=V,
                type="undo.result",
                re=message.id,
                batch_id=None if result.batch is None else result.batch.batch_id,
                undoes=result.undoes,
                dropped=[undo_drop_to_wire(drop) for drop in result.dropped],
            ),
            deliver=True,
        )

    # --- Events ---

    def _events_replay(self, message: m.EventsReplay, session: Session) -> Outcome:
        session.replay_pending = False
        self._withdraw_oversize(_profile(session))
        count = replay_events(
            _profile(session),
            mode=cast(HelloMode, session.mode),
            offers_ready=self._offers_ready(session),
            store=self._store,
            transport=self._sender(session),
        )
        return Outcome(
            m.EventsReplayResult(
                v=V, type="events.replay.result", re=message.id, count=count
            )
        )

    def _events_ack(self, message: m.EventsAck, session: Session) -> Outcome:
        ack_events(
            _profile(session),
            [EventId(event_id) for event_id in message.event_ids],
            store=self._store,
        )
        return Outcome(m.EventsAckResult(v=V, type="events.ack.result", re=message.id))

    # --- Index, search, placement, outline ---

    def _index_pull(self, message: m.IndexPull, session: Session) -> Outcome:
        reply = _fit_page(
            lambda limit: local_index_page(message.cursor, limit, store=self._store),
            lambda rows, cursor: m.IndexPullResult(
                v=V,
                type="index.pull.result",
                re=message.id,
                rows=[local_index_row_to_wire(row) for row in rows],
                next_cursor=cursor,
            ),
            message.limit or m.LARGE_PAGE,
        )
        return Outcome(reply)

    def _search(self, message: m.Search, session: Session) -> Outcome:
        reply = _fit_page(
            lambda limit: search_page(
                Query(message.query),
                message.cursor,
                limit,
                store=self._store,
                embedding=self._embedding,
            ),
            lambda hits, cursor: m.SearchResult(
                v=V,
                type="search.result",
                re=message.id,
                hits=[corpus_hit_to_wire(hit) for hit in hits],
                next_cursor=cursor,
            ),
            message.limit or m.SMALL_PAGE,
        )
        return Outcome(reply)

    def _ask(self, message: m.Ask, session: Session) -> Outcome:
        answer = ask(
            Question(message.question),
            [turn_from_wire(turn) for turn in message.history],
            store=self._store,
            embedding=self._embedding,
            completion=self._completion,
        )
        reply = m.AskResult(
            v=V, type="ask.result", re=message.id, answer=answer_to_wire(answer)
        )
        return Outcome(_fit_answer(reply))

    def _placement_explain(
        self, message: m.PlacementExplain, session: Session
    ) -> Outcome:
        identity = (
            Identity(message.identity)
            if message.identity is not None
            else Identity.from_url(cast(str, message.url))
        )
        placement = explain_placement(identity, store=self._store)
        reply = m.PlacementExplainResult(
            v=V,
            type="placement.explain.result",
            re=message.id,
            reason=placement_to_wire(placement),
        )
        return Outcome(_fit_explanation(reply))

    # --- Diffs ---

    def _diff_propose(self, message: m.DiffPropose, session: Session) -> Outcome:
        diff = request_diff(
            RequestId(message.id),
            DiffKind(message.kind),
            session.role,
            _roots(session),
            store=self._store,
            completion=self._completion,
            clock=self._clock,
            ids=self._ids,
        )
        return Outcome(
            m.DiffProposeResult(
                v=V,
                type="diff.propose.result",
                re=message.id,
                diff=tree_diff_to_wire(diff),
            )
        )

    def _diff_list(self, message: m.DiffList, session: Session) -> Outcome:
        reply = _fit_page(
            lambda limit: list_diffs_page(message.cursor, limit, store=self._store),
            lambda diffs, cursor: m.DiffListResult(
                v=V,
                type="diff.list.result",
                re=message.id,
                diffs=[tree_diff_to_wire(diff) for diff in diffs],
                next_cursor=cursor,
            ),
            message.limit or m.SMALL_PAGE,
        )
        return Outcome(reply)

    def _diff_page(self, message: m.DiffPage, session: Session) -> Outcome:
        diff_id = DiffId(message.diff_id)
        diff, _ = diff_items_page(diff_id, message.cursor, 1, store=self._store)
        reply = _fit_page(
            lambda limit: diff_items_page(
                diff_id, message.cursor, limit, store=self._store
            )[1],
            lambda views, cursor: m.DiffPageResult(
                v=V,
                type="diff.page.result",
                re=message.id,
                diff=tree_diff_to_wire(diff),
                items=[
                    diff_item_to_wire(view.item, batch_state=view.batch_state)
                    for view in views
                ],
                next_cursor=cursor,
            ),
            message.limit or m.SMALL_PAGE,
        )
        return Outcome(reply)

    def _diff_accept(self, message: m.DiffAccept, session: Session) -> Outcome:
        accepted = accept_diff(
            ItemId(message.item_id),
            session.role,
            _roots(session),
            _profile(session),
            conflict=self._conflict(session),
            store=self._store,
            clock=self._clock,
            ids=self._ids,
        )
        if isinstance(accepted, NotWriter | WriterConflict):
            return Outcome(_refused(message.id, accepted))
        if accepted.accepted_at is None or accepted.batch_id is None:
            raise InvalidRequest(f"item {message.item_id} was not accepted")
        return Outcome(
            m.DiffAcceptResult(
                v=V,
                type="diff.accept.result",
                re=message.id,
                item_id=accepted.item_id,
                accepted_at=accepted.accepted_at,
                batch_id=accepted.batch_id,
            ),
            deliver=True,
        )

    def _outline_get(self, message: m.OutlineGet, session: Session) -> Outcome:
        outline = current_outline(_roots(session), store=self._store)
        reply = _fit_page(
            lambda limit: offset_page(
                outline.folders,
                kind="outline",
                params="",
                cursor=message.cursor,
                limit=limit,
            ),
            lambda folders, cursor: m.OutlineGetResult(
                v=V,
                type="outline.get.result",
                re=message.id,
                outline=[outline_folder_to_wire(folder) for folder in folders],
                next_cursor=cursor,
            ),
            message.limit or m.LARGE_PAGE,
        )
        return Outcome(reply)

    def _folder_flags_set(self, message: m.FolderFlagsSet, session: Session) -> Outcome:
        folder = set_folder_flags(
            NodeId(message.node_id),
            None if message.path is None else folder_path_from_wire(message.path),
            message.pinned,
            message.locked,
            session.role,
            _roots(session),
            conflict=self._conflict(session),
            store=self._store,
        )
        if isinstance(folder, NotWriter | WriterConflict):
            return Outcome(_refused(message.id, folder))
        return Outcome(
            m.FolderFlagsSetResult(
                v=V,
                type="folder.flags.set.result",
                re=message.id,
                folder=outline_folder_to_wire(folder),
            )
        )

    def _writer_status(self, message: m.WriterStatus, session: Session) -> Outcome:
        standing = writer_status(
            session.role, self._config.host_id, _roots(session), store=self._store
        )
        return Outcome(
            m.WriterStatusResult(
                v=V,
                type="writer.status.result",
                re=message.id,
                role=standing.role.value,
                host_id=standing.host_id,
                own_marker=standing.own_marker,
                other_writers=list(standing.other_writers),
                conflict=standing.conflict,
            )
        )
