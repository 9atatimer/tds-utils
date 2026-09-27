"""task-030, daemon half: a writer keeps its marker in the owned tree, and a
host configured writer that sees another host's marker refuses every
write-producing use case with a distinct result (DYNOMARK.DESIGN.md, Key
Decisions "Two writers"; Future Considerations "Writer marker"; contract/v1
README, Writer marker: no offers, ``undo``, ``diff.accept`` and
``folder.flags.set`` answered ``writer_conflict``, ``ingest`` accepted and
its job indexed then ``FAILED`` naming the conflict).
"""

import pytest

from dynomark_daemon.app.diffs import accept_diff
from dynomark_daemon.app.flags import set_folder_flags
from dynomark_daemon.app.undo import undo
from dynomark_daemon.app.writer import (
    ensure_writer_marker,
    writer_conflict,
    writer_status,
)
from dynomark_daemon.domain.batch import BatchState, OpCreateFolder
from dynomark_daemon.domain.events import BatchOffered
from dynomark_daemon.domain.ids import BatchId, HostId, ItemId, NodeId, ProfileId
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.placement import FolderChoice
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import Snapshot
from dynomark_daemon.domain.writer import WriterConflict
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._crash import DyingStore
from tests._factories import make_node, make_roots, make_tree
from tests.unit.app._loop import ENRICHMENT, RUST, TREE, Loop

A = ProfileId("profile-a")
MBP = HostId("mbp")
FRESH = make_tree(make_node("10", "1", "Follow Up"))
MARKED = make_tree(
    make_node("11", "1", "Dynomark"),
    make_node("15", "11", "dynomark-writer:mbp"),
)
CONFLICTED = make_tree(
    make_node("11", "1", "Dynomark"),
    make_node("14", "11", "Rust"),
    make_node("16", "11", "dynomark-writer:work-laptop", index=1),
)
CONFLICT = WriterConflict(other_writers=(HostId("work-laptop"),))


def _ensure(
    store: InMemoryCorpusStore, role: HostRole = HostRole.WRITER
) -> BatchId | None:
    batch = ensure_writer_marker(
        role,
        MBP,
        make_roots(),
        A,
        store=store,
        clock=FakeClock(start_ms=1_000),
        ids=SequentialIds(),
    )
    return None if batch is None else batch.batch_id


def _store(tree: Snapshot) -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    store.put_tree_snapshot(tree)
    return store


# --- The marker ---


def test_a_writer_on_a_fresh_tree_offers_its_marker_once() -> None:
    """Given a writer whose tree has no Dynomark, When markers are ensured twice,
    Then one PROPOSED batch creates Dynomark and the marker and is offered;
    the second call proposes nothing while it is pending."""
    store = _store(FRESH)

    first = _ensure(store)
    second = _ensure(store)

    assert first is not None and second is None
    (record,) = store.list_batches()
    assert record.state is BatchState.PROPOSED and record.profile_id == A
    assert [
        op.title for op in record.batch.operations if isinstance(op, OpCreateFolder)
    ] == [
        "Dynomark",
        "dynomark-writer:mbp",
    ]
    offers = [
        p.event for p in store.unacked_events(A) if isinstance(p.event, BatchOffered)
    ]
    assert [o.batch.batch_id for o in offers] == [first]


def test_no_marker_batch_when_present_on_a_reader_or_in_conflict() -> None:
    """Given the marker already in the tree, a reader, or another host's
    marker, When markers are ensured, Then no batch is proposed."""
    assert _ensure(_store(MARKED)) is None
    assert _ensure(_store(FRESH), HostRole.READER) is None
    assert _ensure(_store(CONFLICTED)) is None


def test_writer_status_reports_the_marker_and_the_conflict() -> None:
    """Given a writer's tree holding another host's marker, When its status is
    read, Then it has no own marker, names the other, and is in conflict."""
    standing = writer_status(
        HostRole.WRITER, MBP, make_roots(), store=_store(CONFLICTED)
    )

    assert (standing.own_marker, standing.other_writers, standing.conflict) == (
        False,
        (HostId("work-laptop"),),
        True,
    )
    assert (
        writer_conflict(HostRole.WRITER, MBP, make_roots(), store=_store(MARKED))
        is None
    )


# --- Refusals ---


def test_undo_accept_and_flags_refuse_with_the_conflict() -> None:
    """Given a writer in conflict, When undo, diff acceptance and folder flags
    run, Then each returns the conflict and stores nothing."""
    store = _store(CONFLICTED)
    clock, ids = FakeClock(), SequentialIds()

    results = [
        undo(
            BatchId("batch-1"),
            HostRole.WRITER,
            make_roots(),
            conflict=CONFLICT,
            store=store,
            clock=clock,
            ids=ids,
        ),
        accept_diff(
            ItemId("item-1"),
            HostRole.WRITER,
            make_roots(),
            A,
            conflict=CONFLICT,
            store=store,
            clock=clock,
            ids=ids,
        ),
        set_folder_flags(
            NodeId("14"),
            None,
            None,
            True,
            HostRole.WRITER,
            make_roots(),
            conflict=CONFLICT,
            store=store,
        ),
    ]

    assert results == [CONFLICT, CONFLICT, CONFLICT]
    assert store.list_batches() == [] and store.folder_flags() == {}


def test_a_save_on_a_writer_in_conflict_is_indexed_then_failed() -> None:
    """Given a writer in conflict, When a save's job runs, Then its entry is
    searchable, the job is FAILED naming the conflict, and no batch exists."""
    loop = Loop(
        ScriptedCompletion(
            enrich=[ENRICHMENT],
            choose_folder=[FolderChoice(folder=RUST, rationale="r")],
        ),
        TREE,
    )

    job = loop.run(loop.save(), conflict=CONFLICT)

    assert job.state is JobState.FAILED
    assert job.last_error == "writer_conflict: marker of host work-laptop present"
    assert loop.store.get_entry(job.identity) is not None
    assert loop.store.list_batches() == []


def _is_an_offer(value: object) -> bool:
    return isinstance(value, BatchOffered)


def test_a_marker_killed_before_its_offer_is_offered_on_the_next_snapshot() -> None:
    """Given the daemon was killed after the marker batch was stored and before
    its offer was, When markers are ensured again (the next tree.snapshot),
    Then the marker batch is offered, not held back as pending forever."""
    store = DyingStore()
    store.put_tree_snapshot(FRESH)
    store.kill_at("put_event", _is_an_offer)
    with pytest.raises(SystemExit):
        _ensure(store)

    again = _ensure(store)

    offers = [
        p.event.batch.batch_id
        for p in store.unacked_events(A)
        if isinstance(p.event, BatchOffered)
    ]
    assert again is not None and offers == [again]
