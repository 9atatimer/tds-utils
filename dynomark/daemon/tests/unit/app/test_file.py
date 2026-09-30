"""Behaviors rows: A placement becomes a batch; An out-of-boundary batch is
unconstructible (DYNOMARK.DESIGN.md, Behaviors and Interfaces; Goal 8) --
``file(placement, outline, roots, role) -> WriteBatch or NotWriter``.

The daemon's ``file`` also needs the job (which node the move consumes)
and the store (the batch row, the latest tree for the node's parent id,
the batch.offer event), plus a clock and an id source.
"""

import pytest

from dynomark_daemon.app.errors import TreeNotReady
from dynomark_daemon.app.file import file
from dynomark_daemon.domain.batch import (
    BatchState,
    Expect,
    OpCreate,
    OpCreateFolder,
    OpMove,
    OutsideOwnedRoots,
    Revert,
    WriteBatch,
)
from dynomark_daemon.domain.bookmark import Save
from dynomark_daemon.domain.events import BatchOffered
from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import FolderPath, TreeOutline
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_bookmark,
    make_capture,
    make_job,
    make_node,
    make_outline,
    make_outline_folder,
    make_path,
    make_placement,
    make_roots,
    make_tree,
)

FOLLOW_UP = make_path("Follow Up")
RUST = make_path("Dynomark", "Rust")
ASYNC = make_path("Dynomark", "Rust", "Async")
TREE = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("14", "11", "Rust"),
    make_node("42", "10", "Tokio tutorial", url="https://tokio.rs/tokio/tutorial"),
)
OUTLINE = make_outline(make_outline_folder("Dynomark", "Rust", node_id="14"))


def _placed_job(store: InMemoryCorpusStore) -> Job:
    job = make_job(state=JobState.PLACED)
    store.put_job(job)
    store.put_save(
        job.job_id,
        Save(bookmark=make_bookmark(path=FOLLOW_UP), capture=make_capture()),
    )
    store.put_tree_snapshot(TREE)
    return job


def _file(
    store: InMemoryCorpusStore,
    job: Job,
    folder: FolderPath,
    outline: TreeOutline = OUTLINE,
) -> WriteBatch:
    batch = file(
        make_placement(folder=folder),
        job,
        outline,
        make_roots(),
        HostRole.WRITER,
        store=store,
        clock=FakeClock(start_ms=9_000),
        ids=SequentialIds(),
    )
    assert isinstance(batch, WriteBatch)
    return batch


def test_file_a_placement_under_dynomark_builds_create_folder_move_and_inverse() -> (
    None
):
    """Given a placement under Dynomark in a folder that does not exist yet,
    When filed, Then the batch creates the folder, moves the Follow Up node into
    it, carries the inverse of both, and is stored PROPOSED and offered."""
    store = InMemoryCorpusStore()
    job = _placed_job(store)

    batch = _file(store, job, ASYNC)

    assert batch.operations == (
        OpCreateFolder(index=0, parent=RUST, title="Async"),
        OpMove(
            index=1,
            node_id=NodeId("42"),
            to=ASYNC,
            expect=Expect(parent_id=NodeId("10"), parent_path=FOLLOW_UP),
        ),
    )
    assert batch.inverse == (Revert(of_index=1, back_to=FOLLOW_UP), Revert(of_index=0))
    record = store.get_batch(batch.batch_id)
    assert record is not None
    assert (record.state, record.job_id, record.identity, record.profile_id) == (
        BatchState.PROPOSED,
        job.job_id,
        job.identity,
        job.profile_id,
    )
    (pending,) = store.unacked_events(job.profile_id)
    assert isinstance(pending.event, BatchOffered) and pending.event.batch == batch
    filed = store.get_job(job.job_id)
    assert filed is not None and filed.batch_id == batch.batch_id


def test_file_consumes_the_follow_up_node_instead_of_copying_it() -> None:
    """Given a placement into an existing folder, When filed, Then the batch is
    one move of the saved node itself: nothing is created at the URL, so
    nothing remains in Follow Up."""
    store = InMemoryCorpusStore()
    job = _placed_job(store)

    batch = _file(store, job, RUST)

    assert [type(op) for op in batch.operations] == [OpMove]
    assert not any(isinstance(op, OpCreate) for op in batch.operations)
    (move,) = batch.operations
    assert isinstance(move, OpMove) and move.node_id == job.node_id


def test_file_on_a_fresh_tree_creates_dynomark_and_keeps_it_on_undo() -> None:
    """Given no Dynomark folder yet, When a placement at its root is filed, Then
    the batch creates the owned root (admitted by the boundary) and the inverse
    reverts only the move."""
    store = InMemoryCorpusStore()
    job = _placed_job(store)
    fresh = TreeOutline(root=make_path("Dynomark"), folders=())

    batch = _file(store, job, make_path("Dynomark"), fresh)

    assert batch.operations[0] == OpCreateFolder(
        index=0, parent=FolderPath(root=FOLLOW_UP.root, names=()), title="Dynomark"
    )
    assert batch.inverse == (Revert(of_index=1, back_to=FOLLOW_UP),)


def test_file_a_placement_outside_owned_roots_raises_before_any_batch_exists() -> None:
    """Given a placement path outside OwnedRoots and no accepted item, When
    filed, Then it raises and no batch row, offer or job change exists."""
    store = InMemoryCorpusStore()
    job = _placed_job(store)

    with pytest.raises(OutsideOwnedRoots):
        _file(store, job, make_path("Recipes", "Soup"))

    assert store.list_batches() == []
    assert store.unacked_events(job.profile_id) == []
    assert store.get_job(job.job_id) == job


def test_file_before_any_tree_snapshot_waits_for_one() -> None:
    """Given no tree snapshot recorded yet, When filed, Then it raises
    TreeNotReady (the node's parent id is unknown) and stores nothing."""
    store = InMemoryCorpusStore()
    job = make_job(state=JobState.PLACED)
    store.put_job(job)
    store.put_save(job.job_id, Save(bookmark=make_bookmark(), capture=make_capture()))

    with pytest.raises(TreeNotReady):
        _file(store, job, RUST)

    assert store.list_batches() == []
