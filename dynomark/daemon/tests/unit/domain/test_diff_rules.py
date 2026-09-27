"""The rules a proposed ``DiffItem`` must keep (DYNOMARK.DESIGN.md: glossary
``pinned`` -- "immune to rebuild and audit moves"; ``locked`` -- "never
moved, renamed or merged by any batch"; Multi-device policy -- the rest of
the tree is written "only inside an accepted audit item"; Goal 8), and the
batch an accepted item becomes. Contract v1: a ``DiffItem`` holds 1 to 100
operations with ``operations[i].index == i``; marker folders are excluded
from the outline and from placement.
"""

import pytest

from dynomark_daemon.domain.batch import (
    Expect,
    OpCreate,
    OpCreateFolder,
    OpMove,
    OpRemove,
    OutsideOwnedRoots,
)
from dynomark_daemon.domain.diff import (
    MAX_DESCRIPTION,
    DiffAction,
    DiffKind,
    DiffProposal,
    DiffScope,
    NotAccepted,
    folder_add,
    folder_move,
    item_batch,
    vet,
    violations,
)
from dynomark_daemon.domain.ids import BatchId, NodeId
from dynomark_daemon.domain.tree import FolderPath, RootKey, TreeOutline
from tests._factories import (
    make_diff_item,
    make_outline,
    make_outline_folder,
    make_path,
    make_roots,
)

BAR = FolderPath(root=RootKey.BAR, names=())
RUST = make_path("Dynomark", "Rust")
ASYNC = make_path("Dynomark", "Rust", "Async")
OUTLINE = make_outline(
    make_outline_folder("Dynomark", "Rust", node_id="14"),
    make_outline_folder("Dynomark", "Rust", "Async", node_id="16"),
    make_outline_folder("Dynomark", "Pinned", node_id="17", pinned=True),
    make_outline_folder("Dynomark", "Locked", node_id="18", locked=True),
    make_outline_folder("Dynomark", "Locked", "Inner", node_id="19"),
)
OWN_BAR = TreeOutline(
    root=BAR,
    folders=(
        make_outline_folder(node_id="1"),
        make_outline_folder("Reading", node_id="30"),
    ),
)


def _scope(kind: DiffKind = DiffKind.REBUILD) -> DiffScope:
    return DiffScope(kind=kind, outline=OUTLINE, own_bar=OWN_BAR, roots=make_roots())


def _move(node_id: str, to: FolderPath, parent: FolderPath = RUST) -> OpMove:
    return OpMove(
        index=0,
        node_id=NodeId(node_id),
        to=to,
        expect=Expect(parent_id=NodeId("14"), parent_path=parent),
    )


def _proposal(
    *operations: OpCreateFolder | OpCreate | OpMove | OpRemove,
) -> DiffProposal:
    return DiffProposal(
        action=DiffAction.MOVE, description="tidy", operations=operations
    )


# --- Violations ---


def test_a_rebuild_move_inside_the_owned_tree_keeps_every_rule() -> None:
    """Given a rebuild moving an unpinned folder to another owned folder, When
    checked, Then there is no violation."""
    move = _move("16", make_path("Dynomark", "Concurrency"))

    assert violations((move,), _scope()) == ()


@pytest.mark.parametrize("kind", list(DiffKind))
def test_a_pinned_folder_is_never_moved_or_removed(kind: DiffKind) -> None:
    """Given a rebuild or audit moving or removing a pinned folder, When checked,
    Then each is a violation (pinned is immune to diff moves)."""
    parent = make_path("Dynomark")
    move = _move("17", RUST, parent=parent)
    remove = OpRemove(index=0, node_id=NodeId("17"), expect=Expect(NodeId("11")))

    assert violations((move,), _scope(kind))
    assert violations((remove,), _scope(kind))


def test_a_move_into_a_pinned_folder_is_allowed() -> None:
    """Given a move into a pinned folder, When checked, Then it is allowed (a
    pinned folder is still a placement candidate)."""
    move = _move("16", make_path("Dynomark", "Pinned"))

    assert violations((move,), _scope()) == ()


@pytest.mark.parametrize(
    "operation",
    [
        _move("18", RUST, parent=make_path("Dynomark")),
        _move("19", RUST, parent=make_path("Dynomark", "Locked")),
        _move("16", make_path("Dynomark", "Locked")),
        _move("16", make_path("Dynomark", "Locked", "Inner")),
        OpCreateFolder(index=0, parent=make_path("Dynomark", "Locked"), title="New"),
        OpCreate(
            index=0,
            parent=make_path("Dynomark", "Locked", "Inner"),
            title="t",
            url="https://example.org/",
        ),
    ],
    ids=[
        "move-locked",
        "move-out-of-locked",
        "into-locked",
        "into-under-locked",
        "folder-in-locked",
        "bookmark-under-locked",
    ],
)
def test_a_locked_folder_is_never_touched(
    operation: OpCreateFolder | OpCreate | OpMove,
) -> None:
    """Given an operation that moves, fills or empties a locked folder, When
    checked, Then it is a violation."""
    assert violations((operation,), _scope(DiffKind.AUDIT))


def test_a_rebuild_leaving_the_owned_roots_is_a_violation_an_audit_is_not() -> None:
    """Given a move of a Dynomark folder into the user's own bar folder, When
    checked as rebuild and as audit, Then only the rebuild violates (the rest
    of the tree is written only inside an accepted audit item)."""
    move = _move("16", make_path("Reading"))

    assert violations((move,), _scope(DiffKind.REBUILD))
    assert violations((move,), _scope(DiffKind.AUDIT)) == ()


@pytest.mark.parametrize(
    "operation",
    [
        _move("99", RUST),
        _move("n-Dynomark", make_path("Reading"), parent=BAR),
        _move("1", make_path("Reading"), parent=BAR),
        _move("14", ASYNC, parent=make_path("Dynomark")),
        OpCreateFolder(index=0, parent=RUST, title="dynomark-writer:other"),
        OpCreate(index=0, parent=RUST, title="x", url="javascript:alert(1)"),
    ],
    ids=["unknown-node", "owned-root", "bar-root", "into-itself", "marker", "non-http"],
)
def test_an_operation_the_tree_cannot_take_is_a_violation(
    operation: OpCreateFolder | OpCreate | OpMove,
) -> None:
    """Given a move of a node no outline holds, of an owned root or a browser
    root, into its own subtree, a marker folder, or a non-http(s) bookmark,
    When checked as audit, Then it is a violation."""
    assert violations((operation,), _scope(DiffKind.AUDIT))


# --- Vetting a proposal ---


def test_vet_numbers_the_operations_and_trims_the_description() -> None:
    """Given a proposal whose op indices are off and whose description is long
    and padded, When vetted, Then indices are 0..n-1 and the description is
    stripped and cut to the contract cap."""
    folder = OpCreateFolder(index=7, parent=RUST, title="Tokio")
    move = _move("16", make_path("Dynomark", "Rust", "Tokio"))
    proposal = DiffProposal(
        action=DiffAction.ADD,
        description="  " + "d" * (MAX_DESCRIPTION + 10),
        operations=(folder, move),
    )

    vetted = vet(proposal, _scope())

    assert vetted is not None
    assert [op.index for op in vetted.operations] == [0, 1]
    assert vetted.description == "d" * MAX_DESCRIPTION


@pytest.mark.parametrize(
    "proposal",
    [
        _proposal(),
        _proposal(
            *[OpCreateFolder(index=i, parent=RUST, title=f"f{i}") for i in range(101)]
        ),
        DiffProposal(
            action=DiffAction.ADD,
            description="  ",
            operations=(OpCreateFolder(0, RUST, "x"),),
        ),
        _proposal(_move("17", RUST, parent=make_path("Dynomark"))),
    ],
    ids=["no-ops", "too-many-ops", "blank-description", "moves-pinned"],
)
def test_vet_drops_a_proposal_that_breaks_a_rule(proposal: DiffProposal) -> None:
    """Given a proposal with no or too many ops, no description, or a rule
    violation, When vetted, Then it is dropped."""
    assert vet(proposal, _scope()) is None


# --- Building operations from outline names ---


def test_folder_move_creates_the_missing_target_then_moves_with_expect() -> None:
    """Given a folder and a target one level below an existing folder, When the
    move is built, Then the missing folder is created first and the move
    expects the folder's current parent by id and path."""
    async_folder = OUTLINE.folder_at(ASYNC)
    assert async_folder is not None

    operations = folder_move(
        async_folder, make_path("Dynomark", "Concurrency"), (OUTLINE, OWN_BAR)
    )

    assert operations == (
        OpCreateFolder(index=0, parent=make_path("Dynomark"), title="Concurrency"),
        OpMove(
            index=1,
            node_id=NodeId("16"),
            to=make_path("Dynomark", "Concurrency"),
            expect=Expect(parent_id=NodeId("14"), parent_path=RUST),
        ),
    )


def test_folder_add_creates_each_missing_level_in_the_users_bar() -> None:
    """Given a path two levels below an existing bar folder, When the add is
    built, Then both missing levels are created, top down."""
    operations = folder_add(make_path("Reading", "Rust", "Async"), (OUTLINE, OWN_BAR))

    assert operations == (
        OpCreateFolder(index=0, parent=make_path("Reading"), title="Rust"),
        OpCreateFolder(index=1, parent=make_path("Reading", "Rust"), title="Async"),
    )


# --- The batch an accepted item becomes (Goal 8) ---


def test_an_accepted_item_becomes_a_batch_referencing_it() -> None:
    """Given an item with accepted_at set, When its batch is built, Then the
    batch holds its operations, an inverse, and the item's reference."""
    item = make_diff_item(accepted_at=5)

    batch = item_batch(item, DiffKind.REBUILD, make_roots(), batch_id=BatchId("b-1"))

    assert batch.diff_item_id == item.item_id
    assert batch.operations == item.operations and batch.inverse


def test_an_unaccepted_item_raises_before_a_batch_exists() -> None:
    """Given an item with accepted_at unset, When its batch is built, Then it
    raises."""
    with pytest.raises(NotAccepted):
        item_batch(
            make_diff_item(), DiffKind.AUDIT, make_roots(), batch_id=BatchId("b-1")
        )


def test_an_accepted_rebuild_item_outside_the_owned_roots_raises() -> None:
    """Given an accepted rebuild item moving into the user's bar, When its batch
    is built, Then the boundary raises (only audit items cross it)."""
    item = make_diff_item(accepted_at=5)
    crossing = type(item)(
        item_id=item.item_id,
        diff_id=item.diff_id,
        action=item.action,
        description=item.description,
        operations=(_move("16", make_path("Reading")),),
        accepted_at=5,
    )

    with pytest.raises(OutsideOwnedRoots):
        item_batch(crossing, DiffKind.REBUILD, make_roots(), batch_id=BatchId("b"))
    assert item_batch(crossing, DiffKind.AUDIT, make_roots(), batch_id=BatchId("b"))
