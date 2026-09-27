"""The composition root (coding skill, Section 1.2, Wiring: "exactly one
place per runtime names concrete adapters, and it can be built with every
adapter faked"), and the in-process job loop (Design, Rejections: "A
scheduler port -- an in-process loop with RetryPolicy as a value").
"""

from collections.abc import Sequence
from pathlib import Path

from structlog.testing import capture_logs

from dynomark_daemon.app.ingest import ingest
from dynomark_daemon.container import Daemon, JobLoop, Ports
from dynomark_daemon.domain.bookmark import Bookmark, Capture, CorpusEntry, Enrichment
from dynomark_daemon.domain.chat import DraftAnswer, Question, Turn
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.diff import DiffKind, DiffProposal
from dynomark_daemon.domain.ids import ProfileId
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.placement import EntryRef, FolderChoice, MoveFeedback
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import TreeOutline
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.settings import parse_settings
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ScriptedCompletion
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
