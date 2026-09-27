"""Write batches: path-idempotent operations, their inverse, and receipts."""

from dataclasses import dataclass
from enum import StrEnum

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.ids import (
    BatchId,
    ItemId,
    JobId,
    NodeId,
    ProfileId,
    SnapshotId,
)
from dynomark_daemon.domain.tree import FolderPath, OwnedRoots, Snapshot, TreeOutline


@dataclass(frozen=True, slots=True)
class Expect:
    """The precondition a move or remove re-checks at apply time."""

    parent_id: NodeId
    parent_path: FolderPath | None = None
    empty: bool = False


@dataclass(frozen=True, slots=True)
class OpCreateFolder:
    """Create folder ``title`` in ``parent`` unless it already exists."""

    index: int
    parent: FolderPath
    title: str


@dataclass(frozen=True, slots=True)
class OpCreate:
    """Create a bookmark in ``parent`` unless one with that url exists."""

    index: int
    parent: FolderPath
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class OpMove:
    """Move a node to the end of ``to`` unless it is already directly in it."""

    index: int
    node_id: NodeId
    to: FolderPath
    expect: Expect


@dataclass(frozen=True, slots=True)
class OpRemove:
    """Move a node to ``Graveyard``; nothing is ever hard-deleted."""

    index: int
    node_id: NodeId
    expect: Expect


Operation = OpCreateFolder | OpCreate | OpMove | OpRemove


class BatchState(StrEnum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class SkipReason(StrEnum):
    NODE_MISSING = "node_missing"
    PARENT_MISMATCH = "parent_mismatch"
    NOT_EMPTY = "not_empty"


class FailReason(StrEnum):
    PARENT_MISSING = "parent_missing"
    BROWSER_ERROR = "browser_error"


class RejectReason(StrEnum):
    BOUNDARY = "boundary"
    INVALID = "invalid"
    WRITER_CONFLICT = "writer_conflict"


class UndoDropReason(StrEnum):
    NODE_MOVED = "node_moved"
    NODE_MISSING = "node_missing"
    NOT_EMPTY = "not_empty"


@dataclass(frozen=True, slots=True)
class Revert:
    """One step of a batch's inverse: revert operation ``of_index``.

    A created node goes to ``Graveyard``; a moved or removed node goes back
    to ``back_to``. It names the operation, not a node: the node a create
    mints, and the parent ids every inverse ``Expect`` needs, are known
    only from the receipt and the tree read after it.
    """

    of_index: int
    back_to: FolderPath | None = None


@dataclass(frozen=True, slots=True)
class WriteBatch:
    """Ordered operations plus their inverse, and an optional accepted item."""

    batch_id: BatchId
    operations: tuple[Operation, ...]
    inverse: tuple[Revert, ...]
    diff_item_id: ItemId | None = None


@dataclass(frozen=True, slots=True)
class OpApplied:
    index: int
    node_id: NodeId
    changed: bool


@dataclass(frozen=True, slots=True)
class OpSkipped:
    index: int
    reason: SkipReason


@dataclass(frozen=True, slots=True)
class OpFailed:
    index: int
    reason: FailReason
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReceiptApplied:
    """Every op applied or skipped; ``snapshot`` None means it was omitted."""

    batch_id: BatchId
    applied: tuple[OpApplied, ...]
    skipped: tuple[OpSkipped, ...]
    pre_batch: bool
    snapshot: Snapshot | None


@dataclass(frozen=True, slots=True)
class ReceiptPartial:
    """The applied prefix up to ``failed``; later ops were not tried."""

    batch_id: BatchId
    applied: tuple[OpApplied, ...]
    skipped: tuple[OpSkipped, ...]
    failed: OpFailed
    pre_batch: bool
    snapshot: Snapshot | None


@dataclass(frozen=True, slots=True)
class ReceiptRejected:
    """Nothing was touched."""

    batch_id: BatchId
    reason: RejectReason
    pre_batch: bool
    snapshot: Snapshot | None
    detail: str | None = None


BatchReceipt = ReceiptApplied | ReceiptPartial | ReceiptRejected


@dataclass(frozen=True, slots=True)
class UndoDrop:
    """An inverse operation the undo guard dropped, and why."""

    index: int
    reason: UndoDropReason


@dataclass(frozen=True, slots=True)
class BatchRecord:
    """A ``WriteBatch`` as the daemon keeps it: state, receipt, report."""

    batch: WriteBatch
    state: BatchState
    created_at: int
    profile_id: ProfileId
    job_id: JobId | None = None
    identity: Identity | None = None
    receipt: BatchReceipt | None = None
    snapshot_id: SnapshotId | None = None
    undoes: BatchId | None = None
    undone_by: BatchId | None = None
    report: tuple[UndoDrop, ...] = ()


# --- Building batches (DYNOMARK.DESIGN.md, "Place and file", "Duplicate
# identity"; Goal 8) ---


class OutsideOwnedRoots(Exception):
    """A batch would touch a path outside ``OwnedRoots``; it is never built."""

    def __init__(self, indices: tuple[int, ...]) -> None:
        super().__init__(f"operations {list(indices)} leave the owned roots")
        self.indices = indices


def _creates_owned_root(op: OpCreateFolder, roots: OwnedRoots) -> bool:
    return roots.is_root(op.parent.child(op.title))


def _is_inside_roots(op: Operation, roots: OwnedRoots) -> bool:
    match op:
        case OpCreateFolder():
            return _creates_owned_root(op, roots) or roots.contains(op.parent)
        case OpCreate():
            return roots.contains(op.parent)
        case OpMove():
            source = op.expect.parent_path
            return roots.contains(op.to) and (source is None or roots.contains(source))
        case OpRemove():
            source = op.expect.parent_path
            return source is None or roots.contains(source)


def outside_roots(
    operations: tuple[Operation, ...], roots: OwnedRoots
) -> tuple[int, ...]:
    """Indices of the operations whose target (or known source) folder is not
    inside an owned root; creating an owned root itself is admitted."""
    return tuple(op.index for op in operations if not _is_inside_roots(op, roots))


def admit(operations: tuple[Operation, ...], roots: OwnedRoots) -> None:
    """The boundary policy.

    Raises:
        OutsideOwnedRoots: some operation leaves the owned roots.
    """
    outside = outside_roots(operations, roots)
    if outside:
        raise OutsideOwnedRoots(outside)


def _missing_folders(
    target: FolderPath, outline: TreeOutline
) -> list[tuple[FolderPath, str]]:
    """(parent, title) of each level of ``target`` at or below the outline's
    root that the outline does not hold, top down."""
    first = max(len(outline.root.names), 1)
    return [
        (target.prefix(depth - 1), target.names[depth - 1])
        for depth in range(first, len(target.names) + 1)
        if outline.folder_at(target.prefix(depth)) is None
    ]


def filing_operations(
    target: FolderPath, outline: TreeOutline, *, node_id: NodeId, expect: Expect
) -> tuple[Operation, ...]:
    """Create each missing folder of ``target``, then move the saved node in."""
    creates: list[Operation] = [
        OpCreateFolder(index=i, parent=parent, title=title)
        for i, (parent, title) in enumerate(_missing_folders(target, outline))
    ]
    move = OpMove(index=len(creates), node_id=node_id, to=target, expect=expect)
    return (*creates, move)


def parking_operations(
    roots: OwnedRoots, *, node_id: NodeId, expect: Expect
) -> tuple[Operation, ...]:
    """Make sure ``Graveyard`` exists (path-idempotent), then remove the node."""
    graveyard = roots.graveyard
    if not graveyard.names:
        return (OpRemove(index=0, node_id=node_id, expect=expect),)
    create = OpCreateFolder(
        index=0,
        parent=graveyard.prefix(len(graveyard.names) - 1),
        title=graveyard.names[-1],
    )
    return (create, OpRemove(index=1, node_id=node_id, expect=expect))


def _revert(op: Operation, roots: OwnedRoots) -> Revert | None:
    match op:
        case OpCreateFolder():
            return None if _creates_owned_root(op, roots) else Revert(op.index)
        case OpCreate():
            return Revert(op.index)
        case OpMove() | OpRemove():
            return Revert(op.index, back_to=op.expect.parent_path)


def plan_inverse(
    operations: tuple[Operation, ...], roots: OwnedRoots
) -> tuple[Revert, ...]:
    """The inverse of ``operations``, last first. An owned root the batch
    created is kept: an undo never removes ``Dynomark`` or ``Graveyard``."""
    reverts = (_revert(op, roots) for op in reversed(operations))
    return tuple(r for r in reverts if r is not None)
