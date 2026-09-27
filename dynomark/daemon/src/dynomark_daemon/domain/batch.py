"""Write batches: path-idempotent operations, their inverse, and receipts."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Self

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
    LOCKED = "locked"
    """The step would move or remove a folder the user has locked since
    (Glossary: locked is never moved by any batch)."""


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
    tree_since_receipt: bool = False
    """A ``tree.snapshot`` was recorded after the receipt: the undo guard may
    run (contract v1, Undo guard)."""

    def with_receipt(
        self, receipt: BatchReceipt, snapshot_id: SnapshotId | None
    ) -> Self:
        """The batch once its first receipt is recorded."""
        return replace(
            self, state=receipt_state(receipt), receipt=receipt, snapshot_id=snapshot_id
        )


# --- Receipts (contract v1, Jobs: Receipt -> job) ---


def receipt_state(receipt: BatchReceipt) -> BatchState:
    match receipt:
        case ReceiptApplied():
            return BatchState.APPLIED
        case ReceiptPartial():
            return BatchState.PARTIAL
        case ReceiptRejected():
            return BatchState.REJECTED


def applied_ops(receipt: BatchReceipt) -> tuple[OpApplied, ...]:
    return () if isinstance(receipt, ReceiptRejected) else receipt.applied


def filing_failure(
    batch: WriteBatch, receipt: BatchReceipt, node_id: NodeId | None
) -> str | None:
    """Why the batch did not complete: rejected, failed midway, or (for the
    job's ``node_id``) its filing op -- the move or remove of that node --
    skipped. ``None`` when it did."""
    match receipt:
        case ReceiptRejected():
            return f"batch rejected: {receipt.reason.value}"
        case ReceiptPartial():
            failed = receipt.failed
            return f"batch failed at op {failed.index}: {failed.reason.value}"
        case ReceiptApplied():
            filing = {
                op.index
                for op in batch.operations
                if isinstance(op, OpMove | OpRemove) and op.node_id == node_id
            }
            skipped = [s for s in receipt.skipped if s.index in filing]
            if skipped:
                return (
                    f"filing op {skipped[0].index} skipped: {skipped[0].reason.value}"
                )
            return None


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


def with_graveyard(
    operations: Sequence[Operation], roots: OwnedRoots
) -> tuple[Operation, ...]:
    """``operations`` renumbered, preceded by a path-idempotent create of
    ``Graveyard`` when any of them removes (a ``remove`` into a graveyard that
    does not resolve fails its batch); unchanged when none does."""
    graveyard = roots.graveyard
    if not graveyard.names or not any(isinstance(op, OpRemove) for op in operations):
        return tuple(operations)
    create = OpCreateFolder(
        index=0,
        parent=graveyard.prefix(len(graveyard.names) - 1),
        title=graveyard.names[-1],
    )
    return (create, *(replace(op, index=i + 1) for i, op in enumerate(operations)))


def parking_operations(
    roots: OwnedRoots, *, node_id: NodeId, expect: Expect
) -> tuple[Operation, ...]:
    """Make sure ``Graveyard`` exists (path-idempotent), then remove the node."""
    return with_graveyard((OpRemove(index=0, node_id=node_id, expect=expect),), roots)


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


# --- Inverting an applied batch (Goal 6; The daemon, "Undo") ---


@dataclass(frozen=True, slots=True)
class _Inverting:
    """What inverting one batch knows: the ops it changed, the folders it
    created, and the tree read after it."""

    batch: WriteBatch
    changed: dict[int, OpApplied]
    created: dict[FolderPath, NodeId]
    tree: Snapshot
    roots: OwnedRoots

    def folder_id(self, path: FolderPath) -> NodeId | None:
        return self.created.get(path) or self.tree.resolve(path)

    def left_in(self, op: Operation) -> FolderPath:
        """The folder the op left its node in."""
        match op:
            case OpCreateFolder() | OpCreate():
                return op.parent
            case OpMove():
                return op.to
            case OpRemove():
                return self.roots.graveyard

    def moved_node(self, op: Operation) -> NodeId:
        match op:
            case OpCreateFolder() | OpCreate():
                return self.changed[op.index].node_id
            case OpMove() | OpRemove():
                return op.node_id


def _guard(
    op: Operation, inverting: _Inverting, leaving: set[NodeId]
) -> UndoDropReason | None:
    """Why the undo guard drops the step reverting ``op``: its node is gone,
    is no longer where the batch left it, or is a created folder that other
    items (not moved out by earlier steps) now fill."""
    node_id = inverting.moved_node(op)
    node = inverting.tree.node(node_id)
    if node is None:
        return UndoDropReason.NODE_MISSING
    if node.parent_id != inverting.folder_id(inverting.left_in(op)):
        return UndoDropReason.NODE_MOVED
    if isinstance(op, OpCreateFolder):
        others = [
            c for c in inverting.tree.children(node_id) if c.node_id not in leaving
        ]
        if others:
            return UndoDropReason.NOT_EMPTY
    return None


def _step(
    op: Operation, revert: Revert, inverting: _Inverting, *, index: int
) -> Operation | None:
    """The concrete op reverting ``op``, or ``None`` when a folder it needs
    no longer resolves."""
    left_in = inverting.left_in(op)
    left_id = inverting.folder_id(left_in)
    if left_id is None:
        return None
    match op:
        case OpCreateFolder() | OpCreate():
            expect = Expect(
                parent_id=left_id,
                parent_path=left_in,
                empty=isinstance(op, OpCreateFolder),
            )
            return OpRemove(
                index=index, node_id=inverting.moved_node(op), expect=expect
            )
        case OpMove() | OpRemove():
            back = revert.back_to or inverting.tree.path_of(op.expect.parent_id)
            if back is None:
                return None
            return OpMove(
                index=index,
                node_id=op.node_id,
                to=back,
                expect=Expect(parent_id=left_id, parent_path=left_in),
            )


def _invert(
    batch: WriteBatch,
    applied: Sequence[OpApplied],
    tree: Snapshot,
    roots: OwnedRoots,
    *,
    guarded: bool,
    locked: Collection[NodeId],
) -> tuple[tuple[Operation, ...], tuple[UndoDrop, ...]]:
    changed = {a.index: a for a in applied if a.changed}
    inverting = _Inverting(
        batch=batch,
        changed=changed,
        created={
            op.parent.child(op.title): changed[op.index].node_id
            for op in batch.operations
            if isinstance(op, OpCreateFolder) and op.index in changed
        },
        tree=tree,
        roots=roots,
    )
    ops: list[Operation] = []
    drops: list[UndoDrop] = []
    leaving: set[NodeId] = set()
    for revert in batch.inverse:
        if revert.of_index not in changed:
            continue
        op = batch.operations[revert.of_index]
        if inverting.moved_node(op) in locked:
            drops.append(UndoDrop(op.index, UndoDropReason.LOCKED))
            continue
        reason = _guard(op, inverting, leaving) if guarded else None
        step = None if reason else _step(op, revert, inverting, index=len(ops))
        if step is None:
            drops.append(UndoDrop(op.index, reason or UndoDropReason.NODE_MOVED))
            continue
        ops.append(step)
        leaving.add(inverting.moved_node(op))
    return with_graveyard(ops, roots), tuple(drops)


def invert(
    batch: WriteBatch,
    applied: Sequence[OpApplied],
    tree: Snapshot,
    roots: OwnedRoots,
    *,
    locked: Collection[NodeId] = frozenset(),
) -> tuple[Operation, ...]:
    """The inverse of the ops ``applied`` with ``changed`` true, last first: a
    created node goes to ``Graveyard`` (a folder only if empty; ``Graveyard``
    itself is created first when the inverse removes), a moved or removed
    node goes back. Node ids a create minted come from ``applied``,
    every other folder id from ``tree``. Unguarded (a ``PARTIAL`` prefix):
    the extension re-checks each ``Expect`` when it applies it. A step that
    would move a ``locked`` folder is left out."""
    return _invert(batch, applied, tree, roots, guarded=False, locked=locked)[0]


def guarded_inverse(
    batch: WriteBatch,
    applied: Sequence[OpApplied],
    tree: Snapshot,
    roots: OwnedRoots,
    *,
    locked: Collection[NodeId] = frozenset(),
) -> tuple[tuple[Operation, ...], tuple[UndoDrop, ...]]:
    """The undo of an applied batch against the tree read after its receipt:
    ``invert`` keeping only the steps whose node is still where the batch left
    it, and a folder removal only if nothing else fills the folder; a
    ``locked`` folder is never moved. The rest are dropped and reported, by
    the original op's index."""
    return _invert(batch, applied, tree, roots, guarded=True, locked=locked)
