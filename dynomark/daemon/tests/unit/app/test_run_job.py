"""The job loop's step (DYNOMARK.DESIGN.md, The daemon: "Durable jobs",
"Place and file"; State Machine; Rejections: "an in-process loop with
RetryPolicy as a value", not a scheduler port). ``run_job`` drives one job
through the design's use cases -- process_job, place, file -- as far as it
can go now, and records one ``job.updated`` event for what changed.

Goal 2 (live filing) in miniature: a queued save on the writer ends as a
PROPOSED batch offered to the extension.
"""

from dynomark_daemon.domain.batch import (
    BatchState,
    Expect,
    OpCreateFolder,
    OpRemove,
)
from dynomark_daemon.domain.events import BatchOffered, JobUpdated
from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.placement import FolderChoice, Placement
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.ports.completion import CompletionError
from dynomark_daemon.testing.completion import EnrichCall, ScriptedCompletion
from tests._factories import (
    make_job,
    make_node,
    make_path,
    make_placement,
    make_tree,
)
from tests.unit.app._loop import ENRICHMENT, RUST, TREE, URL, Loop


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


# --- Backfill (contract v1, Jobs: Backfill; design Open Question 3) ---


def test_run_job_backfill_already_in_dynomark_is_filed_in_place() -> None:
    """Given a writer backfilling a bookmark already inside Dynomark, When run,
    Then its placement is recorded at that folder and the job is FILED with no
    batch (how a new writer learns what is already filed)."""
    loop = Loop(ScriptedCompletion(enrich=[ENRICHMENT]), TREE)

    job = loop.run(loop.save(RUST, backfill=True))

    assert (job.state, job.batch_id) == (JobState.FILED, None)
    placement = loop.store.get_placement(job.identity)
    assert placement is not None and placement.folder == RUST
    assert loop.store.list_batches() == []
    assert [type(c) for c in loop.completion.calls] == [EnrichCall]


def test_run_job_backfill_elsewhere_or_on_a_reader_is_only_indexed() -> None:
    """Given a backfill outside Dynomark on the writer, or any backfill on a
    reader, When run, Then the job is INDEXED: searchable, never filed."""
    writer = Loop(ScriptedCompletion(enrich=[ENRICHMENT]), TREE)
    reader = Loop(ScriptedCompletion(enrich=[ENRICHMENT]), TREE)

    outside = writer.run(writer.save(make_path("Recipes"), backfill=True))
    on_reader = reader.run(reader.save(RUST, backfill=True), HostRole.READER)

    assert (outside.state, on_reader.state) == (JobState.INDEXED, JobState.INDEXED)
    assert writer.store.list_batches() == [] == reader.store.list_batches()
    assert writer.store.get_placement(outside.identity) is None
