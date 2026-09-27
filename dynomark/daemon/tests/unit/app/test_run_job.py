"""The job loop's step (DYNOMARK.DESIGN.md, The daemon: "Durable jobs",
"Place and file"; State Machine; Rejections: "an in-process loop with
RetryPolicy as a value", not a scheduler port). ``run_job`` drives one job
through the design's use cases -- process_job, place, file -- as far as it
can go now, and records one ``job.updated`` event for what changed.

Goal 2 (live filing) in miniature: a queued save on the writer ends as a
PROPOSED batch offered to the extension.
"""

from dynomark_daemon.app.ingest import ingest
from dynomark_daemon.app.run import run_job
from dynomark_daemon.domain.batch import (
    BatchState,
    Expect,
    OpCreateFolder,
    OpRemove,
)
from dynomark_daemon.domain.bookmark import Enrichment
from dynomark_daemon.domain.events import BatchOffered, JobUpdated
from dynomark_daemon.domain.ids import NodeId, ProfileId
from dynomark_daemon.domain.job import Job, JobState, RetryPolicy
from dynomark_daemon.domain.placement import FolderChoice, Placement
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import Snapshot
from dynomark_daemon.ports.completion import CompletionError
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import EnrichCall, ScriptedCompletion
from dynomark_daemon.testing.content import FakeFetch
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_bookmark,
    make_capture,
    make_job,
    make_node,
    make_path,
    make_placement,
    make_roots,
    make_tree,
)

PROFILE = ProfileId("profile-a")
URL = "https://tokio.rs/tokio/tutorial"
POLICY = RetryPolicy(attempts=3, initial_backoff_ms=1_000, max_backoff_ms=60_000)
RUST = make_path("Dynomark", "Rust")
TREE = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("14", "11", "Rust"),
    make_node("42", "10", "Tokio tutorial", url="https://tokio.rs/tokio/tutorial"),
)
ENRICHMENT = Enrichment(summary="An async runtime.", tags=("rust",))


class Loop:
    """One daemon's ports, faked, and the job loop's step over them."""

    def __init__(self, completion: ScriptedCompletion, tree: Snapshot | None) -> None:
        self.store = InMemoryCorpusStore()
        self.completion = completion
        self.clock, self.ids = FakeClock(start_ms=1_000), SequentialIds()
        if tree is not None:
            self.store.put_tree_snapshot(tree)

    def save(self) -> Job:
        return ingest(
            make_bookmark(path=make_path("Follow Up")),
            make_capture("Tokio schedules tasks"),
            PROFILE,
            store=self.store,
            clock=self.clock,
            ids=self.ids,
        )

    def run(self, job: Job, role: HostRole = HostRole.WRITER) -> Job:
        current = self.store.get_job(job.job_id)
        assert current is not None
        return run_job(
            current,
            role,
            make_roots(),
            POLICY,
            store=self.store,
            content=FakeFetch({}),
            embedding=HashingEmbedding(),
            completion=self.completion,
            clock=self.clock,
            ids=self.ids,
        )

    def events(self) -> list[object]:
        return [p.event for p in self.store.unacked_events(PROFILE)]


def test_run_job_on_the_writer_takes_a_queued_save_to_a_proposed_batch() -> None:
    """Given a queued save on the writer and a tree snapshot, When the job loop
    runs it, Then it is PLACED with a PROPOSED batch that is offered, and one
    job.updated event carries its latest state."""
    loop = Loop(
        ScriptedCompletion(
            enrich=[ENRICHMENT],
            choose_folder=[FolderChoice(folder=RUST, rationale="rust")],
        ),
        TREE,
    )

    job = loop.run(loop.save())

    assert job.state is JobState.PLACED and job.batch_id is not None
    record = loop.store.get_batch(job.batch_id)
    assert record is not None and record.state is BatchState.PROPOSED
    placement = loop.store.get_placement(job.identity)
    assert placement is not None and placement.folder == RUST
    offers = [e for e in loop.events() if isinstance(e, BatchOffered)]
    updates = [e for e in loop.events() if isinstance(e, JobUpdated)]
    assert [o.batch for o in offers] == [record.batch]
    assert [u.job for u in updates] == [job]


def test_run_job_without_a_tree_snapshot_files_after_the_next_one() -> None:
    """Given no tree snapshot yet, When the job runs, Then it stops PLACED with
    no batch; When a snapshot arrives and it runs again, Then it is filed."""
    loop = Loop(
        ScriptedCompletion(
            enrich=[ENRICHMENT],
            choose_folder=[FolderChoice(folder=RUST, rationale="rust")],
        ),
        None,
    )
    job = loop.save()

    waiting = loop.run(job)
    loop.store.put_tree_snapshot(TREE)
    filed = loop.run(job)

    assert (waiting.state, waiting.batch_id) == (JobState.PLACED, None)
    assert filed.state is JobState.PLACED and filed.batch_id is not None
    assert len(loop.store.list_batches()) == 1


def test_run_job_whose_placement_errors_counts_an_attempt() -> None:
    """Given a completion that errors when choosing a folder, When the job runs,
    Then the attempt is counted and it stays ENRICHED for a retry, with no
    batch."""
    loop = Loop(
        ScriptedCompletion(
            enrich=[ENRICHMENT],
            choose_folder=[CompletionError("model loading", retryable=True)],
        ),
        TREE,
    )

    job = loop.run(loop.save())

    assert (job.state, job.attempts) == (JobState.ENRICHED, 1)
    assert loop.store.list_batches() == []


def _with_filed_original(loop: Loop, *, node_id: str) -> Placement:
    """An earlier save of the same URL, FILED at node ``node_id`` in Rust."""
    original = make_job("job-original", node_id=node_id, state=JobState.FILED)
    loop.store.put_job(original)
    placement = make_placement(original.identity.value, folder=RUST)
    loop.store.put_placement(placement)
    return placement


def test_run_job_parks_a_duplicate_identity_in_the_graveyard() -> None:
    """Given an identity already FILED whose node is in the tree, When a new node
    of it is run on the writer, Then the batch moves the new node to Graveyard
    and the existing placement is unchanged (no completion is asked)."""
    tree = make_tree(*TREE.nodes[3:], make_node("41", "14", "Tokio", url=URL))
    loop = Loop(ScriptedCompletion(enrich=[ENRICHMENT]), tree)
    existing = _with_filed_original(loop, node_id="41")

    job = loop.run(loop.save())

    assert job.state is JobState.PLACED and job.batch_id is not None
    record = loop.store.get_batch(job.batch_id)
    assert record is not None
    assert record.batch.operations == (
        OpCreateFolder(index=0, parent=make_path(), title="Graveyard"),
        OpRemove(
            index=1,
            node_id=NodeId("42"),
            expect=Expect(parent_id=NodeId("10"), parent_path=make_path("Follow Up")),
        ),
    )
    assert loop.store.get_placement(job.identity) == existing
    assert [type(c) for c in loop.completion.calls] == [EnrichCall]


def test_run_job_files_again_an_identity_whose_filed_node_is_gone() -> None:
    """Given an identity FILED earlier whose node is no longer in the tree, When
    a new node of it is run, Then it is placed and filed, not parked."""
    loop = Loop(
        ScriptedCompletion(
            enrich=[ENRICHMENT],
            choose_folder=[FolderChoice(folder=RUST, rationale="rust")],
        ),
        TREE,
    )
    _with_filed_original(loop, node_id="41")

    job = loop.run(loop.save())

    assert job.batch_id is not None
    record = loop.store.get_batch(job.batch_id)
    assert record is not None
    assert not any(isinstance(op, OpRemove) for op in record.batch.operations)
