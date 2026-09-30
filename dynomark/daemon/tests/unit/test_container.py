"""The composition root (coding skill, Section 1.2, Wiring: "exactly one
place per runtime names concrete adapters, and it can be built with every
adapter faked"), and the in-process job loop (Design, Rejections: "A
scheduler port -- an in-process loop with RetryPolicy as a value").
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from structlog.testing import capture_logs

from dynomark_daemon.app.ingest import ingest
from dynomark_daemon.container import Daemon, JobLoop, Ports
from dynomark_daemon.domain.bookmark import Bookmark, Capture, CorpusEntry, Enrichment
from dynomark_daemon.domain.chat import DraftAnswer, Question, Turn
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.diff import DiffKind, DiffProposal
from dynomark_daemon.domain.events import DiffProposed, JobUpdated
from dynomark_daemon.domain.ids import JobId, ProfileId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.placement import EntryRef, FolderChoice, MoveFeedback
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import TreeOutline
from dynomark_daemon.ports.completion import CompletionError, CompletionPort
from dynomark_daemon.settings import parse_settings
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import EnrichCall, ScriptedCompletion
from dynomark_daemon.testing.content import FakeFetch
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests import _wire as wire
from tests._factories import (
    make_bookmark,
    make_capture,
    make_config,
    make_node,
    make_path,
    make_tree,
)

A = ProfileId("profile-a")
ENRICHMENT = Enrichment(summary="An async runtime.", tags=("rust",))
RUST = FolderChoice(folder=make_path("Dynomark", "Rust"), rationale="rust")


class _FailsFirstEnrich:
    """A CompletionPort whose first enrich call fails unexpectedly."""

    def __init__(self, inner: ScriptedCompletion) -> None:
        self._inner = inner
        self._failed = False

    def model(self) -> ModelInfo:
        return self._inner.model()

    def enrich(self, bookmark: Bookmark, capture: Capture) -> Enrichment:
        if not self._failed:
            self._failed = True
            raise RuntimeError("adapter bug")
        return self._inner.enrich(bookmark, capture)

    def choose_folder(
        self,
        entry: CorpusEntry,
        *,
        neighbours: Sequence[EntryRef],
        outline: TreeOutline,
        feedback: Sequence[MoveFeedback],
    ) -> FolderChoice:
        return self._inner.choose_folder(
            entry, neighbours=neighbours, outline=outline, feedback=feedback
        )

    def answer(
        self,
        question: Question,
        *,
        history: Sequence[Turn],
        context: Sequence[CorpusEntry],
    ) -> DraftAnswer:
        return self._inner.answer(question, history=history, context=context)

    def propose_diff(
        self, kind: DiffKind, *, outline: TreeOutline, own_bar: TreeOutline
    ) -> tuple[DiffProposal, ...]:
        return self._inner.propose_diff(kind, outline=outline, own_bar=own_bar)


def _ports(
    completion: CompletionPort, store: InMemoryCorpusStore | None = None
) -> Ports:
    return Ports(
        store=store or InMemoryCorpusStore(),
        embedding=HashingEmbedding(),
        completion=completion,
        content=FakeFetch({}),
        clock=FakeClock(start_ms=1_000),
        ids=SequentialIds(),
    )


def _save(ports: Ports, node_id: str) -> None:
    """Ingest a save of profile A, bound as the writer's profile (its hello)."""
    ports.store.bind_writer_profile(A)
    ingest(
        make_bookmark(f"https://example.org/{node_id}", node_id=node_id),
        make_capture("text"),
        A,
        store=ports.store,
        clock=ports.clock,
        ids=ports.ids,
    )


def test_the_daemon_is_built_with_every_port_faked(tmp_path: Path) -> None:
    """Given settings and fakes behind every port, When the daemon is built,
    Then nothing is opened or bound until it runs (the socket is not there)."""
    settings = parse_settings(
        {"role": "writer"},
        {"DYNOMARK_SOCKET": str(tmp_path / "d.sock")},
        home=tmp_path,
        hostname="mbp",
    )

    daemon = Daemon(settings, _ports(ScriptedCompletion()))

    assert daemon.socket_path == tmp_path / "d.sock"
    assert not (tmp_path / "d.sock").exists()


def test_run_once_advances_every_due_job_and_reports_progress() -> None:
    """Given a queued save and a tree, When the job loop runs once, Then the job
    is PLACED with a batch and the server is told events are waiting."""
    completion = ScriptedCompletion(enrich=[ENRICHMENT], choose_folder=[RUST])
    ports = _ports(completion)
    ports.store.put_tree_snapshot(wire.TREE)
    _save(ports, "42")
    progress: list[int] = []
    loop = JobLoop(make_config(), ports, on_progress=lambda: progress.append(1))

    loop.run_once()

    (job,) = ports.store.list_jobs()
    assert job.state is JobState.PLACED and job.batch_id is not None
    assert progress == [1]


def test_an_unexpected_failure_of_one_job_does_not_stop_the_others() -> None:
    """Given two queued saves and a completion that fails unexpectedly once,
    When the job loop runs once, Then the failure is logged and the other job
    still advances."""
    completion = _FailsFirstEnrich(
        ScriptedCompletion(enrich=[ENRICHMENT], choose_folder=[RUST])
    )
    ports = _ports(completion)
    ports.store.put_tree_snapshot(wire.TREE)
    _save(ports, "1")
    _save(ports, "2")
    loop = JobLoop(make_config(), ports)

    with capture_logs() as logs:
        loop.run_once()

    states = [job.state for job in ports.store.list_jobs()]
    assert states[1] is JobState.PLACED
    assert any(e["event"] == "job.crashed" for e in logs)


class _BrokenFetch:
    """A ContentSourcePort with a bug: every read raises what no port names."""

    def read(self, bookmark: Bookmark) -> Capture:
        raise RuntimeError(f"adapter bug reading {bookmark.url}")


def test_an_unexpected_failure_counts_an_attempt_and_backs_off_until_failed() -> None:
    """Given a capture-less save whose fetch adapter raises an unexpected
    error, When the job loop runs, Then each crash counts a failed attempt
    with its last_error and a job.updated, the job is not due again before
    its RetryPolicy backoff, and it ends FAILED once the attempts are spent:
    no adapter bug pins a job CAPTURING at attempts 0."""
    clock = FakeClock(start_ms=1_000)
    ports = replace(
        _ports(ScriptedCompletion(enrich=[ENRICHMENT])),
        content=_BrokenFetch(),
        clock=clock,
    )
    ports.store.bind_writer_profile(A)
    ingest(
        make_bookmark("https://example.org/42"),
        Capture.none(),
        A,
        store=ports.store,
        clock=clock,
        ids=ports.ids,
    )
    config = make_config()
    policy = config.retry
    loop = JobLoop(config, ports)

    with capture_logs() as logs:
        schedule = loop.run_once()

    (job,) = ports.store.list_jobs()
    assert (job.state, job.attempts) == (JobState.CAPTURING, 1)
    assert job.last_error is not None and "adapter bug" in job.last_error
    assert schedule.due == []
    assert schedule.next_retry_at == job.updated_at + policy.backoff_ms(1)
    assert any(e["event"] == "job.crashed" for e in logs)

    loop.run_once()
    (job,) = ports.store.list_jobs()
    assert job.attempts == 1

    for _ in range(policy.attempts - 1):
        clock.advance(policy.max_backoff_ms)
        loop.run_once()

    (job,) = ports.store.list_jobs()
    assert (job.state, job.attempts) == (JobState.FAILED, policy.attempts)
    updates = [
        p.event.job
        for p in ports.store.unacked_events(A)
        if isinstance(p.event, JobUpdated)
    ]
    assert [u.attempts for u in updates] == list(range(1, policy.attempts + 1))


class _SavesDuringFirstEnrich(ScriptedCompletion):
    """Runs ``arrive`` inside the first enrich call: a save the lane ingests
    while the job loop is busy with a job."""

    def __init__(
        self,
        arrive: Callable[[], None],
        *,
        enrich: Sequence[Enrichment],
        choose_folder: Sequence[FolderChoice],
    ) -> None:
        super().__init__(enrich=enrich, choose_folder=choose_folder)
        self._arrive: Callable[[], None] | None = arrive

    def enrich(self, bookmark: Bookmark, capture: Capture) -> Enrichment:
        arrive, self._arrive = self._arrive, None
        if arrive is not None:
            arrive()
        return super().enrich(bookmark, capture)


def test_a_live_save_ingested_mid_pass_runs_next_ahead_of_the_backfill() -> None:
    """Given three backfill jobs queued, When a live save into Follow Up is
    ingested while the first is being enriched, Then the same pass runs the
    live save next, before the rest of the backfill, and the server is told
    to deliver its offer right after it, not at the end of the pass (Goal 2
    during a first-install backfill)."""
    ports = _ports(ScriptedCompletion())

    def live_save() -> None:
        ingest(
            make_bookmark("https://live.example/", node_id="42"),
            make_capture("live"),
            A,
            store=ports.store,
            clock=ports.clock,
            ids=ports.ids,
        )

    completion = _SavesDuringFirstEnrich(
        live_save, enrich=[ENRICHMENT] * 4, choose_folder=[RUST]
    )
    ports = replace(ports, completion=completion)
    ports.store.bind_writer_profile(A)
    ports.store.put_tree_snapshot(wire.TREE)
    for n in range(3):
        ingest(
            make_bookmark(
                f"https://old.example/{n}", node_id=f"b{n}", path=make_path("Other")
            ),
            make_capture("old"),
            A,
            backfill=True,
            store=ports.store,
            clock=ports.clock,
            ids=ports.ids,
        )

    def enriched() -> list[str]:
        return [
            call.bookmark.node_id
            for call in completion.calls
            if isinstance(call, EnrichCall)
        ]

    delivered_after: list[list[str]] = []
    JobLoop(
        make_config(), ports, on_progress=lambda: delivered_after.append(enriched())
    ).run_once()

    assert enriched() == ["b0", "42", "b1", "b2"]
    assert ["b0", "42"] in delivered_after  # its offer goes out before the rest


class _BoundedStore(InMemoryCorpusStore):
    """Fails the test instead of hanging when a pass never ends."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def get_job(self, job_id: JobId) -> Job | None:
        self.reads += 1
        if self.reads > 50:
            raise AssertionError("the pass keeps running the same job")
        return super().get_job(job_id)


def test_a_job_still_due_after_its_run_waits_for_the_next_pass() -> None:
    """Given a writer with no tree snapshot yet, When the job loop runs a save,
    Then it is PLACED without a batch (waiting for a snapshot) and the pass
    ends rather than running it again and again."""
    ports = _ports(
        ScriptedCompletion(enrich=[ENRICHMENT], choose_folder=[RUST]),
        store=_BoundedStore(),
    )
    _save(ports, "42")

    JobLoop(make_config(), ports).run_once()

    (job,) = ports.store.list_jobs()
    assert (job.state, job.batch_id) == (JobState.PLACED, None)


def test_a_reader_daemon_indexes_and_never_files() -> None:
    """Given a reader configuration, When the job loop runs a save, Then the job
    ends INDEXED with no batch."""
    ports = _ports(ScriptedCompletion(enrich=[ENRICHMENT]))
    _save(ports, "42")

    JobLoop(make_config(role=HostRole.READER), ports).run_once()

    (job,) = ports.store.list_jobs()
    assert (job.state, job.batch_id) == (JobState.INDEXED, None)


def test_the_job_loop_fails_saves_of_a_writer_in_conflict() -> None:
    """Given a writer whose tree holds another host's marker, When the job loop
    runs a save, Then the job is indexed and ends FAILED naming the conflict,
    with no batch (contract v1, Writer marker)."""
    completion = ScriptedCompletion(enrich=[ENRICHMENT], choose_folder=[RUST])
    ports = _ports(completion)
    ports.store.put_tree_snapshot(
        make_tree(
            *[n for n in wire.TREE.nodes[3:] if n.node_id != "13"],
            make_node("15", "11", "dynomark-writer:work-laptop", index=1),
        )
    )
    _save(ports, "42")

    JobLoop(make_config(), ports).run_once()

    (job,) = ports.store.list_jobs()
    assert (job.state, job.batch_id) == (JobState.FAILED, None)
    assert job.last_error == "writer_conflict: marker of host work-laptop present"


def test_the_job_loop_proposes_a_due_rebuild_and_reports_progress() -> None:
    """Given a writer with a daily rebuild cadence, a bound profile and a tree,
    When the job loop runs once, Then a rebuild diff is announced to the
    profile by a diff.proposed event and the server is told."""
    ports = _ports(ScriptedCompletion(propose_diff=[()]))
    ports.store.bind_writer_profile(A)
    ports.store.put_tree_snapshot(wire.TREE)
    progress: list[int] = []
    config = replace(make_config(), rebuild_cadence_ms=86_400_000)

    JobLoop(config, ports, on_progress=lambda: progress.append(1)).run_once()

    events = [p.event for p in ports.store.unacked_events(A)]
    assert [type(e) for e in events] == [DiffProposed] and progress == [1]


def test_run_once_reports_the_retry_a_job_failing_in_this_pass_waits_for() -> None:
    """Given a queued save whose enrichment fails with a retryable error, When
    the job loop runs once, Then the schedule it reports (what the loop sleeps
    on) names that job's retry, not nothing -- so the loop wakes after the
    backoff instead of its idle wait."""
    completion = ScriptedCompletion(
        enrich=[CompletionError("model loading", retryable=True)]
    )
    ports = _ports(completion)
    _save(ports, "42")
    config = make_config()

    schedule = JobLoop(config, ports).run_once()

    (job,) = ports.store.list_jobs()
    assert (job.state, job.attempts) == (JobState.CAPTURING, 1)
    assert schedule.next_retry_at == job.updated_at + config.retry.backoff_ms(1)
