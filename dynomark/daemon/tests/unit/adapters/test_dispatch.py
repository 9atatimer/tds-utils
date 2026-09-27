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
from dynomark_daemon.domain.batch import Expect, OpCreateFolder, OpMove
from dynomark_daemon.domain.bookmark import Enrichment, Identity
from dynomark_daemon.domain.chat import DraftAnswer
from dynomark_daemon.domain.connection import HelloMode
from dynomark_daemon.domain.diff import DiffAction, DiffProposal
from dynomark_daemon.domain.events import BatchOffered, JobUpdated
from dynomark_daemon.domain.ids import EventId, JobId, NodeId, ProfileId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.placement import FolderChoice
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.ports.completion import CompletionError
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
    make_node,
    make_path,
    make_roots,
    make_tree,
)

A = ProfileId("profile-a")
MIB = 1_048_576


class Harness:
    """A dispatcher over fakes and one connection's session."""

    def __init__(
        self,
        role: HostRole = HostRole.WRITER,
        *,
        completion: ScriptedCompletion | None = None,
    ) -> None:
        self.store = InMemoryCorpusStore()
        self.completion = completion or ScriptedCompletion()
        self.transport = RecordingTransport()
        self.clock, self.ids = FakeClock(start_ms=1_000), SequentialIds()
        self.wakes = 0
        self.dispatcher = Dispatcher(
            make_config(role=role),
            store=self.store,
            embedding=HashingEmbedding(),
            completion=self.completion,
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


def test_a_second_hello_answers_the_first_standing_and_writes_nothing() -> None:
    """Given a read_only connection (a newer extension) on an unbound writer,
    When hello arrives again at the daemon's version naming another Follow
    Up, Then the answer repeats the connection's standing (read_only, reader,
    the first Follow Up), the store stays unbound and the profile keeps its
    Follow Up."""
    harness = Harness()
    harness.hello(v=2)
    again = json.loads(wire.hello("h-2"))
    again["follow_up"] = {"root": "bar", "names": ["Elsewhere"]}

    outcome = harness.dispatcher.handle(json.dumps(again).encode(), harness.session)

    reply = outcome.reply
    assert isinstance(reply, m.HelloResult) and not outcome.register
    assert (reply.re, reply.mode, reply.role) == ("h-2", "read_only", "reader")
    assert reply.owned_roots.follow_up.names == ["Follow Up"]
    assert harness.store.writer_profile() is None
    assert harness.store.follow_up_of(A) == make_path("Follow Up")
    assert (harness.session.mode, harness.session.role) == (
        HelloMode.READ_ONLY,
        HostRole.READER,
    )


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


def test_events_go_only_to_the_connection_whose_standing_chose_them() -> None:
    """Given a full writer connection with a snapshot and a batch waiting, and
    a newer read_only connection of the same profile (it superseded the
    first), When events are delivered for the first connection, Then they go
    to that connection alone: the read_only one gets no batch.offer, nor
    anything else chosen by another connection's standing."""
    harness = Harness()
    first = RecordingTransport()
    harness.session = Session(transport=first)
    harness.hello()
    harness.send(wire.tree_snapshot("t-1"))
    newer = RecordingTransport()
    later = Session(transport=newer)
    harness.dispatcher.handle(wire.hello("h-2", v=2), later)
    harness.ingest()
    _placed_job(harness)

    harness.dispatcher.deliver(harness.session)

    assert BatchOffered in [type(e) for e in first.events_for(A)]
    assert newer.pushed == [] and harness.transport.pushed == []


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
    for c in "abcdefghijklmnopqrst":
        harness.store.put_entry(
            make_entry("https://example.org/" + c * 60_000, text="tokio runtime")
        )
    harness.hello()

    reply = harness.send(wire.body("search", "q-1", query="tokio"))

    assert isinstance(reply, m.SearchResult)
    assert len(encode_message(reply)) <= MIB
    assert 0 < len(reply.hits) < 20 and reply.next_cursor is not None


# --- Chat (ask) ---


def test_ask_is_answered_with_citations_on_a_read_only_connection() -> None:
    """Given an entry in the corpus and an extension newer than the daemon, When
    it asks, Then ask.result carries the grounded answer (chat continues in
    read_only)."""
    url = "https://tokio.rs/tokio/tutorial"
    completion = ScriptedCompletion(
        answer=[
            DraftAnswer(
                text="Use select!.",
                cited=(Identity(url),),
                urls=("https://rust-lang.github.io/async-book/",),
            )
        ]
    )
    harness = Harness(completion=completion)
    harness.store.put_entry(make_entry(url, text="tokio cancellation"))
    harness.hello(v=2)

    reply = harness.send(
        wire.body(
            "ask",
            "a-1",
            question="how is cancellation done?",
            history=[{"question": "tokio?", "answer": "a runtime"}],
        )
    )

    assert isinstance(reply, m.AskResult) and reply.re == "a-1"
    assert [c.identity for c in reply.answer.citations] == [url]
    assert reply.answer.external_urls == ["https://rust-lang.github.io/async-book/"]


def test_ask_while_the_model_is_loading_is_busy() -> None:
    """Given a completion that fails retryably, When asked, Then the answer is
    error busy, which the extension retries with the same id."""
    completion = ScriptedCompletion(
        answer=[CompletionError("model loading", retryable=True)]
    )
    harness = Harness(completion=completion)
    harness.hello()

    reply = harness.send(wire.body("ask", "a-2", question="why?", history=[]))

    assert _error(reply) == ("a-2", "busy")


def test_an_ask_answer_is_cut_to_fit_one_mebibyte() -> None:
    """Given retrieved entries whose identities are huge and all cited, When
    asked, Then trailing citations are dropped until the frame fits 1 MiB."""
    identities = [f"https://example.org/{c * 60_000}" for c in "abcdefghijklmnopqrst"]
    completion = ScriptedCompletion(
        answer=[
            DraftAnswer(text="x", cited=tuple(Identity(i) for i in identities), urls=())
        ]
    )
    harness = Harness(completion=completion)
    for identity in identities:
        harness.store.put_entry(make_entry(identity, text="tokio"))
    harness.hello()

    reply = harness.send(wire.body("ask", "a-3", question="tokio", history=[]))

    assert isinstance(reply, m.AskResult)
    assert len(encode_message(reply)) <= MIB
    assert 0 < len(reply.answer.citations) < len(identities)


# --- Diffs ---

TOOLS = DiffProposal(
    action=DiffAction.MOVE,
    description="Move Rust under Tools",
    operations=(
        OpCreateFolder(index=0, parent=make_path("Dynomark"), title="Tools"),
        OpMove(
            index=1,
            node_id=NodeId("14"),
            to=make_path("Dynomark", "Tools"),
            expect=Expect(parent_id=NodeId("11"), parent_path=make_path("Dynomark")),
        ),
    ),
)


def _diff_harness(role: HostRole = HostRole.WRITER) -> Harness:
    harness = Harness(role, completion=ScriptedCompletion(propose_diff=[(TOOLS,)]))
    harness.hello()
    harness.send(wire.tree_snapshot("t-1"))
    return harness


def test_diff_propose_answers_the_header_and_a_repeat_the_same_diff() -> None:
    """Given a writer connection with a tree, When diff.propose arrives twice
    with one id, Then both answers carry the same diff with one unaccepted
    item, and diff.page lists that item."""
    harness = _diff_harness()

    first = harness.send(wire.body("diff.propose", "d-1", kind="rebuild"))
    again = harness.send(wire.body("diff.propose", "d-1", kind="rebuild"))

    assert isinstance(first, m.DiffProposeResult) and first == again.model_copy(
        update={"re": "d-1"}
    )
    assert (first.diff.item_count, first.diff.unaccepted_count) == (1, 1)
    page = harness.send(wire.body("diff.page", "d-2", diff_id=first.diff.diff_id))
    assert isinstance(page, m.DiffPageResult)
    assert [item.description for item in page.items] == ["Move Rust under Tools"]
    listed = harness.send(wire.body("diff.list", "d-3"))
    assert isinstance(listed, m.DiffListResult)
    assert [d.diff_id for d in listed.diffs] == [first.diff.diff_id]


def test_diff_propose_reusing_an_id_with_another_body_is_invalid() -> None:
    """Given a proposed diff, When its request id arrives with another kind,
    Then the answer is error invalid."""
    harness = _diff_harness()
    harness.send(wire.body("diff.propose", "d-1", kind="rebuild"))

    reply = harness.send(wire.body("diff.propose", "d-1", kind="audit"))

    assert _error(reply) == ("d-1", "invalid")


def test_diff_accept_records_the_acceptance_and_offers_its_batch() -> None:
    """Given a proposed diff, When its item is accepted, Then the answer carries
    accepted_at and a batch id, and that batch is offered on the connection."""
    harness = _diff_harness()
    proposed = harness.send(wire.body("diff.propose", "d-1", kind="rebuild"))
    assert isinstance(proposed, m.DiffProposeResult)
    page = harness.send(wire.body("diff.page", "d-2", diff_id=proposed.diff.diff_id))
    assert isinstance(page, m.DiffPageResult)

    reply = harness.send(wire.body("diff.accept", "d-3", item_id=page.items[0].item_id))

    assert isinstance(reply, m.DiffAcceptResult) and reply.accepted_at == 1_000
    offers = [e for e in harness.transport.events_for(A) if isinstance(e, BatchOffered)]
    assert offers[-1].batch.batch_id == reply.batch_id
    assert offers[-1].batch.diff_item_id == page.items[0].item_id


def test_diff_accept_on_a_reader_connection_is_not_writer() -> None:
    """Given a reader daemon, When diff.accept arrives, Then it is answered
    not_writer."""
    harness = Harness(HostRole.READER)
    harness.hello()

    reply = harness.send(wire.body("diff.accept", "d-1", item_id="item-1"))

    assert _error(reply) == ("d-1", "not_writer")


def test_diff_page_of_an_unknown_diff_is_not_found() -> None:
    """Given no diff, When diff.page names one, Then it is answered not_found."""
    harness = _diff_harness()

    reply = harness.send(wire.body("diff.page", "d-1", diff_id="diff-404"))

    assert _error(reply) == ("d-1", "not_found")


# --- Folder flags ---


def test_folder_flags_set_answers_the_folder_and_outline_get_shows_it() -> None:
    """Given a writer connection with a tree, When the Rust folder is locked,
    Then the answer is the folder with its flags, and outline.get shows it."""
    harness = Harness()
    harness.hello()
    harness.send(wire.tree_snapshot("t-1"))

    reply = harness.send(
        wire.body("folder.flags.set", "f-1", node_id="14", locked=True)
    )
    outline = harness.send(wire.body("outline.get", "o-1"))

    assert isinstance(reply, m.FolderFlagsSetResult)
    assert (reply.folder.node_id, reply.folder.locked) == ("14", True)
    assert isinstance(outline, m.OutlineGetResult)
    assert [f.locked for f in outline.outline if f.node_id == "14"] == [True]


def test_folder_flags_set_on_a_reader_connection_is_not_writer() -> None:
    """Given a reader daemon, When folder.flags.set arrives, Then it is answered
    not_writer."""
    harness = Harness(HostRole.READER)
    harness.hello()

    reply = harness.send(
        wire.body("folder.flags.set", "f-1", node_id="14", pinned=True)
    )

    assert _error(reply) == ("f-1", "not_writer")


# --- Writer marker (task-030) ---

OTHER_MARKER = make_tree(
    *[n for n in wire.TREE.nodes[3:] if n.node_id != "13"],
    make_node("15", "11", "dynomark-writer:work-laptop", index=1),
)


def test_the_first_snapshot_of_a_fresh_tree_offers_the_writer_marker() -> None:
    """Given a writer connection, When its first snapshot has no Dynomark, Then
    a batch creating Dynomark and this host's marker is offered."""
    harness = Harness()
    harness.hello()

    harness.send(
        wire.tree_snapshot("t-1", make_tree(make_node("10", "1", "Follow Up")))
    )

    (offer,) = [
        e for e in harness.transport.events_for(A) if isinstance(e, BatchOffered)
    ]
    titles = [getattr(op, "title", None) for op in offer.batch.operations]
    assert titles == ["Dynomark", "dynomark-writer:mbp"]


def test_writer_status_reports_another_hosts_marker_as_a_conflict() -> None:
    """Given a writer whose tree holds another host's marker, When writer.status
    arrives, Then the answer names it and says conflict."""
    harness = Harness()
    harness.hello()
    harness.send(wire.tree_snapshot("t-1", OTHER_MARKER))

    reply = harness.send(wire.body("writer.status", "w-1"))

    assert isinstance(reply, m.WriterStatusResult)
    assert (reply.role, reply.host_id, reply.own_marker) == ("writer", "mbp", False)
    assert (reply.other_writers, reply.conflict) == (["work-laptop"], True)


@pytest.mark.parametrize(
    ("message_type", "fields"),
    [
        ("undo", {"batch_id": "batch-1"}),
        ("diff.accept", {"item_id": "item-1"}),
        ("folder.flags.set", {"node_id": "14", "locked": True}),
    ],
)
def test_a_writer_in_conflict_refuses_writes_with_writer_conflict(
    message_type: str, fields: dict[str, object]
) -> None:
    """Given a writer that sees another host's marker, When undo, diff.accept or
    folder.flags.set arrives, Then it is answered writer_conflict."""
    harness = Harness()
    harness.hello()
    harness.send(wire.tree_snapshot("t-1", OTHER_MARKER))

    reply = harness.send(wire.body(message_type, "x-1", **fields))

    assert _error(reply) == ("x-1", "writer_conflict")


def test_a_writer_in_conflict_offers_no_batch() -> None:
    """Given a filed job's batch waiting, When the connection's snapshot holds
    another host's marker, Then no batch.offer is sent."""
    harness = Harness()
    harness.hello()
    harness.store.put_tree_snapshot(wire.TREE)
    harness.ingest()
    _placed_job(harness)

    harness.send(wire.tree_snapshot("t-1", OTHER_MARKER))

    offers = [e for e in harness.transport.events_for(A) if isinstance(e, BatchOffered)]
    assert offers == []


def test_an_observed_move_is_logged_with_whether_it_became_feedback() -> None:
    """Given a writer connection, When a user move between owned folders and an
    extension move arrive, Then each is logged move.observed with its node,
    origin and whether it was recorded as feedback (the week-of-use repair log
    and the integration e2e read it)."""
    harness = Harness()
    harness.hello()
    move = {
        "node_id": "15",
        "url": "https://doc.rust-lang.org/book/",
        "from": {"root": "bar", "names": ["Dynomark", "Rust"]},
        "to": {"root": "bar", "names": ["Dynomark", "Reading"]},
        "origin": "user",
        "observed_at": 1_790_000_005_000,
    }

    with capture_logs() as logs:
        harness.send(wire.body("move.observed", "mv-1", move=move))
        harness.send(
            wire.body(
                "move.observed",
                "mv-2",
                move={**move, "origin": "extension", "observed_at": 1_790_000_006_000},
            )
        )

    observed = [
        (e["node_id"], e["origin"], e["feedback"])
        for e in logs
        if e["event"] == "move.observed"
    ]
    assert observed == [("15", "user", True), ("15", "extension", False)]
