"""The transport adapter's request side: one frame body in, one answer out.

contract/v1/README.md: Connection lifecycle (hello first, admission order,
mode), Envelope ("Every request X is answered by exactly one frame"),
Delivery and replay (events, offers only after a tree.snapshot on the
connection), Roles and errors (the closed code set), Size limits (no frame
over 1 MiB to the extension). Driven with fakes behind every port.
"""

import json

import pytest
from structlog.testing import capture_logs

from dynomark_daemon.adapters.dispatch import Dispatcher, Session
from dynomark_daemon.app.run import run_job
from dynomark_daemon.domain.bookmark import Enrichment
from dynomark_daemon.domain.connection import HelloMode
from dynomark_daemon.domain.events import BatchOffered, JobUpdated
from dynomark_daemon.domain.ids import EventId, JobId, ProfileId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.placement import FolderChoice
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.content import FakeFetch
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from dynomark_daemon.testing.transport import RecordingTransport
from dynomark_daemon.wire import messages as m
from dynomark_daemon.wire.codec import encode_message
from tests import _wire as wire
from tests._factories import (
    make_bookmark,
    make_capture,
    make_config,
    make_entry,
    make_path,
    make_roots,
)

A = ProfileId("profile-a")
MIB = 1_048_576


class Harness:
    """A dispatcher over fakes and one connection's session."""

    def __init__(self, role: HostRole = HostRole.WRITER) -> None:
        self.store = InMemoryCorpusStore()
        self.transport = RecordingTransport()
        self.clock, self.ids = FakeClock(start_ms=1_000), SequentialIds()
        self.wakes = 0
        self.dispatcher = Dispatcher(
            make_config(role=role),
            store=self.store,
            embedding=HashingEmbedding(),
            completion=ScriptedCompletion(),
            clock=self.clock,
            ids=self.ids,
            transport=self.transport,
            wake=self._wake,
        )
        self.session = Session()

    def _wake(self) -> None:
        self.wakes += 1

    def send(self, body: bytes) -> m.AnyMessage:
        outcome = self.dispatcher.handle(body, self.session)
        assert outcome.reply is not None, "the connection was closed"
        if outcome.deliver:
            self.dispatcher.deliver(self.session)
        return outcome.reply

    def hello(self, *, v: int = 1) -> m.AnyMessage:
        return self.send(wire.hello(v=v))

    def ingest(self, request_id: str = "i-1") -> m.AnyMessage:
        return self.send(
            wire.ingest(request_id, make_bookmark(), make_capture("Tokio text"))
        )


def _error(reply: m.AnyMessage) -> tuple[str | None, str]:
    assert isinstance(reply, m.Error), reply
    return reply.re, reply.code


# --- Admission (Connection lifecycle, step 3) ---


def test_a_request_before_hello_is_answered_hello_required() -> None:
    """Given a new connection, When a request other than hello arrives, Then it
    is answered error hello_required with its id."""
    harness = Harness()

    reply = harness.send(wire.body("status", "s-1"))

    assert _error(reply) == ("s-1", "hello_required")


def test_hello_answers_role_mode_and_owned_roots_and_registers() -> None:
    """Given a writer daemon, When the first profile says hello, Then the answer
    serves it writer in full mode with the owned roots, and the connection is
    registered for the profile (it supersedes an older one)."""
    harness = Harness()

    outcome = harness.dispatcher.handle(wire.hello(), harness.session)

    reply = outcome.reply
    assert isinstance(reply, m.HelloResult)
    assert (reply.re, reply.role, reply.mode, reply.host_id) == (
        "h-1",
        "writer",
        "full",
        "mbp",
    )
    assert reply.owned_roots.dynomark.names == ["Dynomark"]
    assert outcome.register
    assert (harness.session.profile_id, harness.session.mode) == (A, HelloMode.FULL)


def test_a_second_hello_is_answered_and_changes_nothing() -> None:
    """Given a full connection, When hello arrives again with a newer version,
    Then it is answered and the connection keeps its mode."""
    harness = Harness()
    harness.hello()

    outcome = harness.dispatcher.handle(wire.hello("h-2", v=2), harness.session)

    assert isinstance(outcome.reply, m.HelloResult) and not outcome.register
    assert harness.session.mode is HelloMode.FULL


def test_a_non_frozen_message_of_another_version_is_a_version_mismatch() -> None:
    """Given a full connection, When a status request says v 2, Then it is
    answered version_mismatch before the schema runs."""
    harness = Harness()
    harness.hello()

    reply = harness.send(json.dumps({"v": 2, "type": "status", "id": "s-2"}).encode())

    assert _error(reply) == ("s-2", "version_mismatch")


def test_a_read_only_connection_searches_but_does_not_ingest() -> None:
    """Given an extension newer than the daemon (read_only), When it searches
    and then ingests, Then the search is served and the ingest refused."""
    harness = Harness()
    harness.hello(v=2)

    searched = harness.send(wire.body("search", "q-1", query="tokio"))
    ingested = harness.ingest("i-9")

    assert isinstance(searched, m.SearchResult)
    assert _error(ingested) == ("i-9", "version_mismatch")


@pytest.mark.parametrize("body", [b"[]", b"not json", b"\xff"])
def test_a_body_that_is_not_a_json_object_closes_without_answer(body: bytes) -> None:
    """Given any connection, When a body is not a JSON object, Then there is no
    answer: the connection closes."""
    harness = Harness()

    outcome = harness.dispatcher.handle(body, harness.session)

    assert outcome.reply is None


def test_a_body_failing_the_schema_is_invalid_with_its_id() -> None:
    """Given a full connection, When an ingest lacks its bookmark, Then it is
    answered error invalid with the request's id."""
    harness = Harness()
    harness.hello()

    reply = harness.send(wire.body("ingest", "i-2", backfill=False))

    assert _error(reply) == ("i-2", "invalid")


def test_a_response_sent_by_the_extension_is_invalid() -> None:
    """Given a full connection, When the extension sends a message that is not
    a request, Then it is answered invalid (only requests go that way)."""
    harness = Harness()
    harness.hello()

    reply = harness.send(
        json.dumps({"v": 1, "type": "events.ack.result", "re": "x"}).encode()
    )

    assert _error(reply) == (None, "invalid")


# --- Requests ---


def test_ingest_queues_one_job_and_wakes_the_job_loop() -> None:
    """Given a full connection, When a save is ingested twice with two ids, Then
    both answers carry the same QUEUED job and the job loop is woken."""
    harness = Harness()
    harness.hello()

    first, second = harness.ingest("i-1"), harness.ingest("i-2")

    assert isinstance(first, m.IngestResult) and isinstance(second, m.IngestResult)
    assert first.job == second.job and first.job.state == "QUEUED"
    assert len(harness.store.list_jobs()) == 1 and harness.wakes >= 1


def test_ingest_logs_when_the_save_was_received() -> None:
    """Given a full connection, When a new save is ingested, Then an
    ingest.received event names the job and the time it arrived (Goal 2's
    interval starts there)."""
    harness = Harness()
    harness.hello()

    with capture_logs() as logs:
        reply = harness.ingest()

    assert isinstance(reply, m.IngestResult)
    assert {
        "event": "ingest.received",
        "job_id": reply.job.job_id,
        "received_at": 1_000,
    }.items() <= next(e for e in logs if e["event"] == "ingest.received").items()


def test_undo_on_a_reader_connection_is_not_writer() -> None:
    """Given a reader daemon, When undo arrives, Then it is answered not_writer."""
    harness = Harness(HostRole.READER)
    harness.hello()

    reply = harness.send(wire.body("undo", "u-1", batch_id="batch-1"))

    assert _error(reply) == ("u-1", "not_writer")


def test_a_receipt_for_an_unknown_batch_is_not_found() -> None:
    """Given a full writer connection, When a receipt names no known batch, Then
    it is answered not_found."""
    harness = Harness()
    harness.hello()

    reply = harness.send(wire.applied_receipt("r-1", "batch-404", ["16", "42"]))

    assert _error(reply) == ("r-1", "not_found")


def test_a_foreign_cursor_is_stale() -> None:
    """Given a full connection, When index.pull presents a job.list cursor, Then
    it is answered stale_cursor."""
    harness = Harness()
    harness.hello()

    reply = harness.send(
        wire.body("index.pull", "p-1", cursor="job~0000000000000000~job-1")
    )

    assert _error(reply) == ("p-1", "stale_cursor")


@pytest.mark.parametrize(
    ("message_type", "fields"),
    [
        ("ask", {"question": "why?", "history": []}),
        ("diff.propose", {"kind": "audit"}),
        ("writer.status", {}),
    ],
)
def test_a_request_this_daemon_does_not_serve_yet_is_invalid(
    message_type: str, fields: dict[str, object]
) -> None:
    """Given a full connection, When an MVP request arrives, Then it is still
    answered: error invalid naming what is not served."""
    harness = Harness()
    harness.hello()

    reply = harness.send(wire.body(message_type, "x-1", **fields))

    assert _error(reply) == ("x-1", "invalid")


class _BrokenStore(InMemoryCorpusStore):
    def get_job(self, job_id: JobId) -> Job | None:
        raise RuntimeError("disk on fire")


def test_an_unexpected_failure_is_answered_internal() -> None:
    """Given a store that fails, When a request hits it, Then it is answered
    error internal (retryable) rather than left unanswered."""
    harness = Harness()
    harness.store = _BrokenStore()
    harness.dispatcher = Dispatcher(
        make_config(),
        store=harness.store,
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(),
        clock=harness.clock,
        ids=harness.ids,
        transport=harness.transport,
        wake=lambda: None,
    )
    harness.hello()

    reply = harness.send(wire.body("job.retry", "j-1", job_id="job-1"))

    assert _error(reply) == ("j-1", "internal")


# --- Events and offers (Delivery and replay) ---


def _placed_job(harness: Harness) -> None:
    """Drive one saved job to an offered batch through the application."""
    job = harness.store.list_jobs()[0]
    run_job(
        job,
        HostRole.WRITER,
        make_roots(),
        make_config().retry,
        store=harness.store,
        content=FakeFetch({}),
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(
            enrich=[Enrichment(summary="An async runtime.", tags=("rust",))],
            choose_folder=[
                FolderChoice(folder=make_path("Dynomark", "Rust"), rationale="rust")
            ],
        ),
        clock=harness.clock,
        ids=harness.ids,
    )


def test_no_batch_offer_before_a_tree_snapshot_on_the_connection() -> None:
    """Given a writer connection with a filed job's batch waiting, When events
    are delivered before and after the connection's first tree.snapshot, Then
    the offer goes out only after it (job events go out before)."""
    harness = Harness()
    harness.hello()
    harness.store.put_tree_snapshot(wire.TREE)
    harness.ingest()
    _placed_job(harness)

    harness.dispatcher.deliver(harness.session)
    before = [type(e) for e in harness.transport.events_for(A)]
    harness.send(wire.tree_snapshot("t-1"))
    after = [type(e) for e in harness.transport.events_for(A)]

    assert BatchOffered not in before and JobUpdated in before
    assert BatchOffered in after


def test_events_replay_resends_unacknowledged_events_and_counts_them() -> None:
    """Given job events already pushed, When events.replay arrives, Then they
    are pushed again and the answer counts them; after events.ack they are
    not replayed."""
    harness = Harness(HostRole.READER)
    harness.hello()
    harness.ingest()
    queued = harness.store.list_jobs(state=JobState.QUEUED)[0]
    harness.store.put_event(A, JobUpdated(event_id=EventId("evt-q"), job=queued))
    harness.dispatcher.deliver(harness.session)
    pushed = len(harness.transport.pushed)

    replayed = harness.send(wire.body("events.replay", "e-1"))
    event_ids = [e.event_id for e in harness.transport.events_for(A)]
    harness.send(wire.body("events.ack", "e-2", event_ids=event_ids))
    again = harness.send(wire.body("events.replay", "e-3"))

    assert isinstance(replayed, m.EventsReplayResult) and replayed.count == pushed
    assert isinstance(again, m.EventsReplayResult) and again.count == 0


# --- Frame size (Size limits) ---


def test_a_search_page_is_shortened_to_fit_one_mebibyte() -> None:
    """Given hits whose identities are huge, When a full page is asked for,
    Then the answer is at most 1 MiB and its cursor leads to the rest."""
    harness = Harness()
    for c in "abcdefghij":
        harness.store.put_entry(
            make_entry("https://example.org/" + c * 60_000, text="tokio runtime")
        )
    harness.hello()

    reply = harness.send(wire.body("search", "q-1", query="tokio"))

    assert isinstance(reply, m.SearchResult)
    assert len(encode_message(reply)) <= MIB
    assert 0 < len(reply.hits) < 10 and reply.next_cursor is not None
