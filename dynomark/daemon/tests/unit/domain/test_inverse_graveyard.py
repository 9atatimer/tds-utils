"""An inverse that removes something makes sure ``Graveyard`` exists first
(Goal 6: "a removal is a move to Graveyard"; contract/v1 README, Write
batches: a ``remove`` whose graveyard does not resolve fails the batch
``PARTIAL``, and a ``create_folder`` of an owned root is admitted "to create
Dynomark and Graveyard on a fresh tree").

Found by the integration e2e: on a fresh tree nothing had created
``Graveyard``, so the undo of the first filing moved the bookmark back and
then failed on removing the folder it had created.
"""

from dynomark_daemon.domain.batch import (
    Expect,
    OpApplied,
    OpCreateFolder,
    OpMove,
    OpRemove,
    WriteBatch,
    guarded_inverse,
    invert,
    plan_inverse,
)
from dynomark_daemon.domain.ids import BatchId, NodeId
from tests._factories import make_node, make_path, make_roots, make_tree

FOLLOW_UP = make_path("Follow Up")
READING = make_path("Dynomark", "Reading")
CREATE_READING = OpCreateFolder(index=0, parent=make_path("Dynomark"), title="Reading")
MOVE_IN = OpMove(
    index=1,
    node_id=NodeId("42"),
    to=READING,
    expect=Expect(parent_id=NodeId("10"), parent_path=FOLLOW_UP),
)
FILING = WriteBatch(
    batch_id=BatchId("batch-1"),
    operations=(CREATE_READING, MOVE_IN),
    inverse=plan_inverse((CREATE_READING, MOVE_IN), make_roots()),
)
APPLIED = (
    OpApplied(index=0, node_id=NodeId("16"), changed=True),
    OpApplied(index=1, node_id=NodeId("42"), changed=True),
)
AFTER = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("16", "11", "Reading"),
    make_node("42", "16", "Tokio tutorial", url="http://127.0.0.1:4321/tokio"),
)
CREATE_GRAVEYARD = OpCreateFolder(index=0, parent=make_path(), title="Graveyard")


def test_guarded_inverse_creates_graveyard_before_removing_into_it() -> None:
    """Given a filing that created a folder, on a tree with no Graveyard, When
    its undo is computed, Then the inverse first creates Graveyard, then moves
    the bookmark back, then removes the folder into Graveyard."""
    operations, dropped = guarded_inverse(FILING, APPLIED, AFTER, make_roots())

    assert dropped == ()
    assert operations[0] == CREATE_GRAVEYARD
    assert [type(op) for op in operations] == [OpCreateFolder, OpMove, OpRemove]
    assert [op.index for op in operations] == [0, 1, 2]


def test_prefix_inverse_creates_graveyard_before_removing_into_it() -> None:
    """Given a filing whose folder was created before its move failed, When the
    inverse of the applied prefix is computed, Then it creates Graveyard
    before removing the folder."""
    tree = make_tree(
        make_node("10", "1", "Follow Up"),
        make_node("11", "1", "Dynomark", index=1),
        make_node("16", "11", "Reading"),
    )

    operations = invert(FILING, APPLIED[:1], tree, make_roots())

    assert operations[0] == CREATE_GRAVEYARD
    assert isinstance(operations[1], OpRemove)
    assert operations[1].node_id == NodeId("16")


def test_an_inverse_that_removes_nothing_creates_no_graveyard() -> None:
    """Given a batch that only moved a node, When it is undone, Then the
    inverse is the move back alone."""
    move = OpMove(
        index=0,
        node_id=NodeId("42"),
        to=READING,
        expect=Expect(parent_id=NodeId("10"), parent_path=FOLLOW_UP),
    )
    batch = WriteBatch(
        batch_id=BatchId("batch-2"),
        operations=(move,),
        inverse=plan_inverse((move,), make_roots()),
    )
    applied = (OpApplied(index=0, node_id=NodeId("42"), changed=True),)

    operations, _ = guarded_inverse(batch, applied, AFTER, make_roots())

    assert [type(op) for op in operations] == [OpMove]


def test_the_prefix_inverse_leaves_a_locked_folder_where_it_is() -> None:
    """Given a batch that created a folder now locked, When the unguarded
    inverse of its applied prefix is built, Then the bookmark goes back and
    the locked folder is not removed (locked: never moved by any batch)."""
    operations = invert(
        FILING, APPLIED, AFTER, make_roots(), locked=frozenset({NodeId("16")})
    )

    assert [type(op) for op in operations] == [OpMove]
    assert operations[0].node_id == NodeId("42")
