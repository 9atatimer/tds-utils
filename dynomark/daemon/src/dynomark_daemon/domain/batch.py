"""Write batches: path-idempotent operations, their inverse, and receipts."""

from dataclasses import dataclass
from enum import StrEnum

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.ids import BatchId, ItemId, JobId, NodeId, SnapshotId
from dynomark_daemon.domain.tree import FolderPath, Snapshot


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
class WriteBatch:
    """Ordered operations plus their inverse, and an optional accepted item."""

    batch_id: BatchId
    operations: tuple[Operation, ...]
    inverse: tuple[Operation, ...]
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
    job_id: JobId | None = None
    identity: Identity | None = None
    receipt: BatchReceipt | None = None
    snapshot_id: SnapshotId | None = None
    undoes: BatchId | None = None
    undone_by: BatchId | None = None
    report: tuple[UndoDrop, ...] = ()
