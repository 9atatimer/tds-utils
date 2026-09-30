"""Behaviors rows: A batch is undone; Undo skips a moved or vanished node;
Undo leaves a non-empty folder; and the undo half of A reader host never
writes (DYNOMARK.DESIGN.md, Behaviors and Interfaces; The daemon, "Undo";
Goal 6) -- ``undo(batch_id, role, *, store) -> WriteBatch or NotWriter``.

Contract v1 pins the rest (Write batches: Undo guard; the idempotency
table): the guard runs only against a tree snapshot received after the
receipt (``busy`` before one); at most one inverse per batch; an
all-dropped answer is not recorded. ``undo`` also takes OwnedRoots (the
inverse of a remove needs the graveyard).
"""

from dataclasses import replace

import pytest

from dynomark_daemon.app.errors import Busy, InvalidRequest
from dynomark_daemon.app.flags import set_folder_flags
from dynomark_daemon.app.tree import record_tree_snapshot
from dynomark_daemon.app.undo import Undone, undo
from dynomark_daemon.domain.batch import (
    BatchRecord,
    BatchState,
    Expect,
    OpCreateFolder,
    OpMove,
    OpRemove,
    ReceiptApplied,
    UndoDrop,
    UndoDropReason,
)
from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import Snapshot, SnapshotNode
from dynomark_daemon.domain.writer import WriterConflict
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._crash import DyingStore
from tests._factories import make_node, make_path, make_roots, make_tree
from tests.unit.app._filed import ASYNC, CREATED, MOVED, RUST, TREE, Daemon

FOLLOW_UP = make_path("Follow Up")
BASE = TREE.nodes[3:6]  # Follow Up 10, Dynomark 11, Rust 14
URL = "https://tokio.rs/tokio/tutorial"
CREATE_GRAVEYARD = OpCreateFolder(index=0, parent=make_path(), title="Graveyard")
"""Every inverse that removes creates Graveyard first (path-idempotent)."""
MOVE_BACK = OpMove(
    index=1,
    node_id=NodeId("42"),
    to=FOLLOW_UP,
    expect=Expect(parent_id=NodeId("16"), parent_path=ASYNC),
)
REMOVE_ASYNC = OpRemove(
    index=2,
    node_id=NodeId("16"),
    expect=Expect(parent_id=NodeId("14"), parent_path=RUST, empty=True),
)


def _after(*nodes: SnapshotNode) -> Snapshot:
    return make_tree(*BASE, *nodes, taken_at=TREE.taken_at + 60_000)


def _applied_daemon(
    tree_after: Snapshot | None, store: InMemoryCorpusStore | None = None
) -> Daemon:
    """The filing batch APPLIED; then, if given, the tree the extension sends."""
    daemon = Daemon(store)
    daemon.receive(
        ReceiptApplied(
            batch_id=daemon.batch.batch_id,
            applied=(CREATED, MOVED),
            skipped=(),
            pre_batch=True,
            snapshot=TREE,
        )
    )
    if tree_after is not None:
        record_tree_snapshot(tree_after, HostRole.WRITER, store=daemon.store)
    return daemon


def _undo(
    daemon: Daemon, role: HostRole = HostRole.WRITER
) -> Undone | NotWriter | WriterConflict:
    return undo(
        daemon.batch.batch_id,
        role,
        make_roots(),
        store=daemon.store,
        clock=daemon.clock,
        ids=daemon.ids,
    )


def test_undo_reverts_every_operation_and_not_a_later_user_edit() -> None:
    """Given an APPLIED batch and a user edit to a node the batch did not touch,
    When undone, Then the inverse moves the node back and removes the created
    folder, is stored PROPOSED and offered, and the user's node is no target."""
    daemon = _applied_daemon(
        _after(
            make_node("16", "14", "Async"),
            make_node("42", "16", "Tokio tutorial", url=URL),
            make_node("50", "14", "User's own", index=1, url="https://user.example/"),
        )
    )

    result = _undo(daemon)

    assert isinstance(result, Undone)
    assert result.batch is not None
    assert result.batch.operations == (CREATE_GRAVEYARD, MOVE_BACK, REMOVE_ASYNC)
    assert result.dropped == ()
    targets = {
        op.node_id
        for op in result.batch.operations
        if isinstance(op, OpMove | OpRemove)
    }
    assert NodeId("50") not in targets
    record = daemon.store.get_batch(result.batch.batch_id)
    assert record is not None
    assert (record.state, record.undoes) == (BatchState.PROPOSED, daemon.batch.batch_id)
    assert [o.batch for o in daemon.offers()] == [result.batch]


def test_undo_never_moves_a_folder_the_user_has_locked_since() -> None:
    """Given the folder the batch created was since locked (Glossary: locked
    is "never moved, renamed or merged by any batch"), When undone, Then the
    bookmark still goes back but the folder's removal is dropped and
    reported as locked."""
    daemon = _applied_daemon(
        _after(
            make_node("16", "14", "Async"),
            make_node("42", "16", "Tokio tutorial", url=URL),
        )
    )
    set_folder_flags(
        NodeId("16"),
        None,
        None,
        True,
        HostRole.WRITER,
        make_roots(),
        store=daemon.store,
    )

    result = _undo(daemon)

    assert isinstance(result, Undone) and result.batch is not None
    assert result.batch.operations == (replace(MOVE_BACK, index=0),)
    assert result.dropped == (UndoDrop(0, UndoDropReason.LOCKED),)


def test_undo_drops_and_reports_a_node_the_user_moved_since() -> None:
    """Given the filed node was since moved by the user, When undone, Then its
    move back is dropped and reported, and the now-empty folder is removed."""
    daemon = _applied_daemon(
        _after(
            make_node("16", "14", "Async"),
            make_node("42", "14", "Tokio tutorial", index=1, url=URL),
        )
    )

    result = _undo(daemon)

    assert isinstance(result, Undone) and result.batch is not None
    assert result.dropped == (UndoDrop(index=1, reason=UndoDropReason.NODE_MOVED),)
    assert result.batch.operations == (
        CREATE_GRAVEYARD,
        OpRemove(index=1, node_id=NodeId("16"), expect=REMOVE_ASYNC.expect),
    )
    record = daemon.store.get_batch(result.batch.batch_id)
    assert record is not None and record.report == result.dropped


def test_undo_drops_and_reports_a_node_that_vanished() -> None:
    """Given the filed node was since deleted, When undone, Then its move back
    is dropped as missing."""
    daemon = _applied_daemon(_after(make_node("16", "14", "Async")))

    result = _undo(daemon)

    assert isinstance(result, Undone)
    assert UndoDrop(index=1, reason=UndoDropReason.NODE_MISSING) in result.dropped


def test_undo_leaves_a_created_folder_that_now_holds_other_items() -> None:
    """Given a folder the batch created now holds another item, When undone,
    Then the node is moved back but the folder's removal is dropped and
    reported."""
    daemon = _applied_daemon(
        _after(
            make_node("16", "14", "Async"),
            make_node("42", "16", "Tokio tutorial", url=URL),
            make_node("51", "16", "Later save", index=1, url="https://later.example/"),
        )
    )

    result = _undo(daemon)

    assert isinstance(result, Undone) and result.batch is not None
    assert result.batch.operations == (replace(MOVE_BACK, index=0),)
    assert result.dropped == (UndoDrop(index=0, reason=UndoDropReason.NOT_EMPTY),)


def test_undo_twice_returns_the_one_recorded_inverse() -> None:
    """Given a batch already undone, When undone again, Then the same recorded
    inverse is returned and no second one exists (idempotent on batch_id)."""
    daemon = _applied_daemon(
        _after(
            make_node("16", "14", "Async"),
            make_node("42", "16", "Tokio tutorial", url=URL),
        )
    )

    first, again = _undo(daemon), _undo(daemon)

    assert first == again
    assert len(daemon.store.list_batches()) == 2


def test_undo_that_drops_everything_is_not_recorded() -> None:
    """Given every inverse step would be dropped, When undone, Then the answer
    has no batch, lists the drops, and nothing is recorded, so a later undo
    re-evaluates."""
    daemon = _applied_daemon(
        _after(
            make_node("16", "14", "Async"),
            make_node("51", "16", "Later save", url="https://later.example/"),
        )
    )

    result = _undo(daemon)

    assert isinstance(result, Undone) and result.batch is None
    assert {d.reason for d in result.dropped} == {
        UndoDropReason.NODE_MISSING,
        UndoDropReason.NOT_EMPTY,
    }
    record = daemon.store.get_batch(daemon.batch.batch_id)
    assert record is not None and record.undone_by is None
    assert len(daemon.store.list_batches()) == 1


def test_undo_before_a_tree_snapshot_after_the_receipt_is_busy() -> None:
    """Given an APPLIED batch and no tree snapshot received since its receipt,
    When undone, Then it raises Busy (retry after the next snapshot)."""
    daemon = _applied_daemon(None)

    with pytest.raises(Busy):
        _undo(daemon)


def test_undo_of_a_batch_not_applied_is_invalid() -> None:
    """Given a batch still PROPOSED, When undone, Then it raises InvalidRequest."""
    daemon = Daemon()

    with pytest.raises(InvalidRequest):
        _undo(daemon)


def test_undo_on_a_reader_is_not_writer_and_stores_no_batch() -> None:
    """Given role reader, When undo runs, Then the result is NotWriter and no
    batch row exists beyond the original."""
    daemon = _applied_daemon(_after(make_node("16", "14", "Async")))

    result = _undo(daemon, HostRole.READER)

    assert isinstance(result, NotWriter)
    assert len(daemon.store.list_batches()) == 1


def _links_an_inverse(value: object) -> bool:
    """The write that records ``original.undone_by``."""
    return isinstance(value, BatchRecord) and value.undone_by is not None


def test_an_undo_retried_after_a_kill_before_the_link_offers_one_inverse() -> None:
    """Given the daemon was killed after an undo stored and offered the inverse
    and before it recorded the original's ``undone_by``, When the undo is
    retried, Then exactly one inverse of the batch is offered and it is the
    one the original names."""
    store = DyingStore()
    daemon = _applied_daemon(
        _after(
            make_node("16", "14", "Async"),
            make_node("42", "16", "Tokio tutorial", url=URL),
        ),
        store,
    )
    store.kill_at("put_batch", _links_an_inverse)
    with pytest.raises(SystemExit):
        _undo(daemon)

    again = _undo(daemon)

    assert isinstance(again, Undone) and again.batch is not None
    inverses = [r for r in store.list_batches() if r.undoes == daemon.batch.batch_id]
    assert [r.batch for r in inverses] == [again.batch]
    assert [o.batch for o in daemon.offers()] == [again.batch]
    original = store.get_batch(daemon.batch.batch_id)
    assert original is not None and original.undone_by == again.batch.batch_id
