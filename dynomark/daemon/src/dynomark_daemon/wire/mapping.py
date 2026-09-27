"""Wire <-> domain mapping for contract v1.

The only place that knows both a wire model and a domain value. Inbound
(extension -> daemon) values map ``*_from_wire``; outbound ones
``*_to_wire``. Where the domain value holds everything its wire model
does, both directions exist and are lossless; values the daemon only
sends (``Job``, ``WriteBatch``, a ``TreeDiff`` header, a batch summary, an
event) map outbound only, because the domain holds more than the wire
(a job's profile, a batch's inverse, a diff's items).

Wire models are strict: lists, not tuples; plain strings for enums.
"""

from typing import Literal, cast

from dynomark_daemon.domain.batch import (
    BatchReceipt,
    BatchRecord,
    BatchState,
    Expect,
    FailReason,
    OpApplied,
    OpCreate,
    OpCreateFolder,
    Operation,
    OpFailed,
    OpMove,
    OpRemove,
    OpSkipped,
    ReceiptApplied,
    ReceiptPartial,
    ReceiptRejected,
    RejectReason,
    SkipReason,
    UndoDrop,
    UndoDropReason,
    WriteBatch,
)
from dynomark_daemon.domain.bookmark import Bookmark, Capture, CaptureSource, Identity
from dynomark_daemon.domain.chat import Answer, Citation, Turn
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.diff import DiffItem, TreeDiff
from dynomark_daemon.domain.events import BatchOffered, DiffProposed, Event, JobUpdated
from dynomark_daemon.domain.ids import BatchId, FeedbackId, NodeId
from dynomark_daemon.domain.job import Job
from dynomark_daemon.domain.placement import (
    EntryRef,
    Move,
    MoveOrigin,
    Placement,
    PlacementReason,
)
from dynomark_daemon.domain.search import Hit, HitTier, LocalIndexRow
from dynomark_daemon.domain.tree import (
    FolderPath,
    NodeKind,
    OutlineFolder,
    OwnedRoots,
    RootIds,
    RootKey,
    Snapshot,
    SnapshotNode,
)
from dynomark_daemon.wire import messages as m
from dynomark_daemon.wire import values as w
from dynomark_daemon.wire.base import CONTRACT_VERSION

# --- Tree ---


def folder_path_from_wire(path: w.FolderPath) -> FolderPath:
    return FolderPath(root=RootKey(path.root), names=tuple(path.names))


def folder_path_to_wire(path: FolderPath) -> w.FolderPath:
    return w.FolderPath(root=path.root.value, names=list(path.names))


def owned_roots_from_wire(roots: w.OwnedRoots) -> OwnedRoots:
    return OwnedRoots(
        follow_up=folder_path_from_wire(roots.follow_up),
        dynomark=folder_path_from_wire(roots.dynomark),
        graveyard=folder_path_from_wire(roots.graveyard),
    )


def owned_roots_to_wire(roots: OwnedRoots) -> w.OwnedRoots:
    return w.OwnedRoots(
        follow_up=folder_path_to_wire(roots.follow_up),
        dynomark=folder_path_to_wire(roots.dynomark),
        graveyard=folder_path_to_wire(roots.graveyard),
    )


def outline_folder_from_wire(folder: w.OutlineFolder) -> OutlineFolder:
    return OutlineFolder(
        node_id=NodeId(folder.node_id),
        path=folder_path_from_wire(folder.path),
        pinned=folder.pinned,
        locked=folder.locked,
        item_count=folder.item_count,
    )


def outline_folder_to_wire(folder: OutlineFolder) -> w.OutlineFolder:
    return w.OutlineFolder(
        node_id=folder.node_id,
        path=folder_path_to_wire(folder.path),
        pinned=folder.pinned,
        locked=folder.locked,
        item_count=folder.item_count,
    )


def _snapshot_node_from_wire(node: w.SnapshotNode) -> SnapshotNode:
    return SnapshotNode(
        node_id=NodeId(node.id),
        parent_id=None if node.parent_id is None else NodeId(node.parent_id),
        index=node.index,
        kind=NodeKind(node.kind),
        title=node.title,
        date_added=node.date_added,
        url=node.url,
        truncated=node.truncated is True,
    )


def _snapshot_node_to_wire(node: SnapshotNode) -> w.SnapshotNode:
    return w.SnapshotNode(
        id=node.node_id,
        parent_id=node.parent_id,
        index=node.index,
        kind=node.kind.value,
        title=node.title,
        url=node.url,
        truncated=True if node.truncated else None,
        date_added=node.date_added,
    )


def snapshot_from_wire(snapshot: w.Snapshot) -> Snapshot:
    ids = snapshot.root_ids
    return Snapshot(
        taken_at=snapshot.taken_at,
        root_ids=RootIds(
            bar=NodeId(ids.bar),
            other=NodeId(ids.other),
            mobile=None if ids.mobile is None else NodeId(ids.mobile),
            menu=None if ids.menu is None else NodeId(ids.menu),
        ),
        nodes=tuple(_snapshot_node_from_wire(node) for node in snapshot.nodes),
    )


def snapshot_to_wire(snapshot: Snapshot) -> w.Snapshot:
    ids = snapshot.root_ids
    return w.Snapshot(
        taken_at=snapshot.taken_at,
        root_ids=w.RootIds(
            bar=ids.bar, other=ids.other, mobile=ids.mobile, menu=ids.menu
        ),
        nodes=[_snapshot_node_to_wire(node) for node in snapshot.nodes],
    )


# --- Bookmark, capture, job ---


def bookmark_from_wire(bookmark: w.Bookmark) -> Bookmark:
    return Bookmark(
        node_id=NodeId(bookmark.node_id),
        url=bookmark.url,
        title=bookmark.title,
        path=folder_path_from_wire(bookmark.path),
        date_added=bookmark.date_added,
    )


def bookmark_to_wire(bookmark: Bookmark) -> w.Bookmark:
    return w.Bookmark(
        node_id=bookmark.node_id,
        url=bookmark.url,
        title=bookmark.title,
        path=folder_path_to_wire(bookmark.path),
        date_added=bookmark.date_added,
    )


def capture_from_wire(capture: w.Capture) -> Capture:
    return Capture(
        source=CaptureSource(capture.source), text=capture.text, title=capture.title
    )


def capture_to_wire(capture: Capture) -> w.Capture:
    """Raises ``pydantic.ValidationError`` for ``fetch``: it never goes on the wire."""
    return w.Capture(
        source=cast(w.ExtensionCaptureSource, capture.source.value),
        text=capture.text,
        title=capture.title,
    )


def job_to_wire(job: Job) -> w.Job:
    return w.Job(
        job_id=job.job_id,
        node_id=job.node_id,
        identity=job.identity.value,
        state=job.state.value,
        seq=job.seq,
        attempts=job.attempts,
        backfill=job.backfill,
        capture_source=(
            None if job.capture_source is None else job.capture_source.value
        ),
        last_error=job.last_error,
        batch_id=job.batch_id,
    )


# --- Operations and batches ---


def _expect_from_wire(expect: w.Expect) -> Expect:
    return Expect(
        parent_id=NodeId(expect.parent_id),
        parent_path=(
            None
            if expect.parent_path is None
            else folder_path_from_wire(expect.parent_path)
        ),
        empty=expect.empty is True,
    )


def _expect_to_wire(expect: Expect) -> w.Expect:
    return w.Expect(
        parent_id=expect.parent_id,
        parent_path=(
            None
            if expect.parent_path is None
            else folder_path_to_wire(expect.parent_path)
        ),
        empty=True if expect.empty else None,
    )


def operation_from_wire(
    op: w.OpCreateFolder | w.OpCreate | w.OpMove | w.OpRemove,
) -> Operation:
    match op:
        case w.OpCreateFolder():
            return OpCreateFolder(
                index=op.index, parent=folder_path_from_wire(op.parent), title=op.title
            )
        case w.OpCreate():
            return OpCreate(
                index=op.index,
                parent=folder_path_from_wire(op.parent),
                title=op.title,
                url=op.url,
            )
        case w.OpMove():
            return OpMove(
                index=op.index,
                node_id=NodeId(op.node_id),
                to=folder_path_from_wire(op.to),
                expect=_expect_from_wire(op.expect),
            )
        case w.OpRemove():
            return OpRemove(
                index=op.index,
                node_id=NodeId(op.node_id),
                expect=_expect_from_wire(op.expect),
            )


def operation_to_wire(
    op: Operation,
) -> w.OpCreateFolder | w.OpCreate | w.OpMove | w.OpRemove:
    match op:
        case OpCreateFolder():
            return w.OpCreateFolder(
                op="create_folder",
                index=op.index,
                parent=folder_path_to_wire(op.parent),
                title=op.title,
            )
        case OpCreate():
            return w.OpCreate(
                op="create",
                index=op.index,
                parent=folder_path_to_wire(op.parent),
                title=op.title,
                url=op.url,
            )
        case OpMove():
            return w.OpMove(
                op="move",
                index=op.index,
                node_id=op.node_id,
                to=folder_path_to_wire(op.to),
                expect=_expect_to_wire(op.expect),
            )
        case OpRemove():
            return w.OpRemove(
                op="remove",
                index=op.index,
                node_id=op.node_id,
                expect=_expect_to_wire(op.expect),
            )


def write_batch_to_wire(batch: WriteBatch) -> w.WriteBatch:
    """The batch as offered: its operations; the inverse stays in the store."""
    return w.WriteBatch(
        batch_id=batch.batch_id,
        operations=[operation_to_wire(op) for op in batch.operations],
        diff_item_id=batch.diff_item_id,
    )


def _applied_from_wire(op: w.OpApplied) -> OpApplied:
    return OpApplied(index=op.index, node_id=NodeId(op.node_id), changed=op.changed)


def _applied_to_wire(op: OpApplied) -> w.OpApplied:
    return w.OpApplied(index=op.index, node_id=op.node_id, changed=op.changed)


def _skipped_from_wire(op: w.OpSkipped) -> OpSkipped:
    return OpSkipped(index=op.index, reason=SkipReason(op.reason))


def _skipped_to_wire(op: OpSkipped) -> w.OpSkipped:
    return w.OpSkipped(index=op.index, reason=op.reason.value)


def _snapshot_or_omitted(
    snapshot: Snapshot | None,
) -> tuple[w.Snapshot | None, bool | None]:
    if snapshot is None:
        return None, True
    return snapshot_to_wire(snapshot), None


def receipt_from_wire(
    receipt: w.ReceiptApplied | w.ReceiptPartial | w.ReceiptRejected,
) -> BatchReceipt:
    """A receipt; ``snapshot`` None stands for ``snapshot_omitted``."""
    batch_id = BatchId(receipt.batch_id)
    snapshot = (
        None if receipt.snapshot is None else snapshot_from_wire(receipt.snapshot)
    )
    match receipt:
        case w.ReceiptApplied():
            return ReceiptApplied(
                batch_id=batch_id,
                applied=tuple(_applied_from_wire(op) for op in receipt.applied),
                skipped=tuple(_skipped_from_wire(op) for op in receipt.skipped),
                pre_batch=receipt.pre_batch,
                snapshot=snapshot,
            )
        case w.ReceiptPartial():
            return ReceiptPartial(
                batch_id=batch_id,
                applied=tuple(_applied_from_wire(op) for op in receipt.applied),
                skipped=tuple(_skipped_from_wire(op) for op in receipt.skipped),
                failed=OpFailed(
                    index=receipt.failed.index,
                    reason=FailReason(receipt.failed.reason),
                    detail=receipt.failed.detail,
                ),
                pre_batch=receipt.pre_batch,
                snapshot=snapshot,
            )
        case w.ReceiptRejected():
            return ReceiptRejected(
                batch_id=batch_id,
                reason=RejectReason(receipt.reason),
                pre_batch=receipt.pre_batch,
                snapshot=snapshot,
                detail=receipt.detail,
            )


def receipt_to_wire(
    receipt: BatchReceipt,
) -> w.ReceiptApplied | w.ReceiptPartial | w.ReceiptRejected:
    snapshot, omitted = _snapshot_or_omitted(receipt.snapshot)
    match receipt:
        case ReceiptApplied():
            return w.ReceiptApplied(
                state="APPLIED",
                batch_id=receipt.batch_id,
                snapshot=snapshot,
                snapshot_omitted=omitted,
                pre_batch=receipt.pre_batch,
                applied=[_applied_to_wire(op) for op in receipt.applied],
                skipped=[_skipped_to_wire(op) for op in receipt.skipped],
            )
        case ReceiptPartial():
            return w.ReceiptPartial(
                state="PARTIAL",
                batch_id=receipt.batch_id,
                snapshot=snapshot,
                snapshot_omitted=omitted,
                pre_batch=receipt.pre_batch,
                applied=[_applied_to_wire(op) for op in receipt.applied],
                skipped=[_skipped_to_wire(op) for op in receipt.skipped],
                failed=w.OpFailed(
                    index=receipt.failed.index,
                    reason=receipt.failed.reason.value,
                    detail=receipt.failed.detail,
                ),
            )
        case ReceiptRejected():
            return w.ReceiptRejected(
                state="REJECTED",
                batch_id=receipt.batch_id,
                snapshot=snapshot,
                snapshot_omitted=omitted,
                pre_batch=receipt.pre_batch,
                reason=receipt.reason.value,
                detail=receipt.detail,
            )


def undo_drop_from_wire(drop: w.UndoDrop) -> UndoDrop:
    return UndoDrop(index=drop.index, reason=UndoDropReason(drop.reason))


def undo_drop_to_wire(drop: UndoDrop) -> w.UndoDrop:
    return w.UndoDrop(index=drop.index, reason=drop.reason.value)


def batch_summary_to_wire(record: BatchRecord) -> w.BatchSummary:
    return w.BatchSummary(
        batch_id=record.batch.batch_id,
        state=record.state.value,
        created_at=record.created_at,
        job_id=record.job_id,
        identity=None if record.identity is None else record.identity.value,
        diff_item_id=record.batch.diff_item_id,
        undoes=record.undoes,
        undone_by=record.undone_by,
    )


# --- Moves ---


def move_from_wire(move: w.Move) -> Move:
    return Move(
        node_id=NodeId(move.node_id),
        from_path=folder_path_from_wire(move.from_),
        to_path=folder_path_from_wire(move.to),
        origin=MoveOrigin(move.origin),
        observed_at=move.observed_at,
        url=move.url,
    )


def move_to_wire(move: Move) -> w.Move:
    return w.Move(
        node_id=move.node_id,
        url=move.url,
        from_=folder_path_to_wire(move.from_path),
        to=folder_path_to_wire(move.to_path),
        origin=move.origin.value,
        observed_at=move.observed_at,
    )


# --- Search and index ---


def local_index_row_from_wire(row: w.LocalIndexRow) -> LocalIndexRow:
    return LocalIndexRow(
        identity=Identity(row.identity),
        title=row.title,
        path=folder_path_from_wire(row.path),
        tags=tuple(row.tags),
        summary=row.summary,
    )


def local_index_row_to_wire(row: LocalIndexRow) -> w.LocalIndexRow:
    return w.LocalIndexRow(
        identity=row.identity.value,
        title=row.title,
        path=folder_path_to_wire(row.path),
        tags=list(row.tags),
        summary=row.summary,
    )


def hit_from_wire(hit: w.Hit) -> Hit:
    return Hit(
        identity=Identity(hit.identity),
        title=hit.title,
        path=folder_path_from_wire(hit.path),
        score=hit.score,
        tier=HitTier(hit.tier),
    )


def corpus_hit_to_wire(hit: Hit) -> w.CorpusHit:
    """A ``search.result`` hit; raises ``pydantic.ValidationError`` unless corpus."""
    return w.CorpusHit(
        identity=hit.identity.value,
        title=hit.title,
        path=folder_path_to_wire(hit.path),
        score=hit.score,
        tier=cast(Literal["corpus"], hit.tier.value),
    )


# --- Chat and placement ---


def citation_from_wire(ref: w.EntryRef) -> Citation:
    return Citation(
        identity=Identity(ref.identity),
        title=ref.title,
        path=folder_path_from_wire(ref.path),
    )


def citation_to_wire(citation: Citation | EntryRef) -> w.EntryRef:
    return w.EntryRef(
        identity=citation.identity.value,
        title=citation.title,
        path=folder_path_to_wire(citation.path),
    )


def turn_from_wire(turn: w.Turn) -> Turn:
    return Turn(question=turn.question, answer=turn.answer)


def turn_to_wire(turn: Turn) -> w.Turn:
    return w.Turn(question=turn.question, answer=turn.answer)


def answer_from_wire(answer: w.Answer) -> Answer:
    return Answer(
        text=answer.text,
        citations=tuple(citation_from_wire(c) for c in answer.citations),
        external_urls=tuple(answer.external_urls),
    )


def answer_to_wire(answer: Answer) -> w.Answer:
    return w.Answer(
        text=answer.text,
        citations=[citation_to_wire(c) for c in answer.citations],
        external_urls=list(answer.external_urls),
    )


def placement_from_wire(reason: w.PlacementReason) -> Placement:
    return Placement(
        identity=Identity(reason.identity),
        reason=PlacementReason(
            folder=folder_path_from_wire(reason.folder),
            neighbours=tuple(
                EntryRef(
                    identity=Identity(n.identity),
                    title=n.title,
                    path=folder_path_from_wire(n.path),
                )
                for n in reason.neighbours
            ),
            rationale=reason.rationale,
            feedback_ids=tuple(FeedbackId(f) for f in reason.feedback_ids),
            model_id=reason.model_id,
        ),
        created_at=reason.created_at,
    )


def placement_to_wire(placement: Placement) -> w.PlacementReason:
    """``placement.explain.result``'s reason: the placement and why."""
    reason = placement.reason
    return w.PlacementReason(
        identity=placement.identity.value,
        folder=folder_path_to_wire(reason.folder),
        neighbours=[citation_to_wire(n) for n in reason.neighbours],
        rationale=reason.rationale,
        feedback_ids=list(reason.feedback_ids),
        model_id=reason.model_id,
        created_at=placement.created_at,
    )


# --- Diffs, status ---


def tree_diff_to_wire(diff: TreeDiff) -> w.TreeDiff:
    """The diff header: counts derived from its items."""
    return w.TreeDiff(
        diff_id=diff.diff_id,
        kind=diff.kind.value,
        proposed_at=diff.proposed_at,
        item_count=len(diff.items),
        unaccepted_count=sum(item.accepted_at is None for item in diff.items),
    )


def diff_item_to_wire(
    item: DiffItem, *, batch_state: BatchState | None = None
) -> w.DiffItem:
    """A diff item; ``batch_state`` is its batch's state, from the store."""
    return w.DiffItem(
        item_id=item.item_id,
        diff_id=item.diff_id,
        action=item.action.value,
        description=item.description,
        operations=[operation_to_wire(op) for op in item.operations],
        accepted_at=item.accepted_at,
        batch_id=item.batch_id,
        batch_state=(None if batch_state is None else batch_state.value),
    )


def model_info_from_wire(info: w.ModelInfo) -> ModelInfo:
    return ModelInfo(model_id=info.id, local=info.local)


def model_info_to_wire(info: ModelInfo) -> w.ModelInfo:
    return w.ModelInfo(id=info.model_id, local=info.local)


# --- Events ---


def event_to_wire(event: Event) -> m.JobUpdated | m.BatchOffer | m.DiffProposed:
    match event:
        case JobUpdated():
            return m.JobUpdated(
                v=CONTRACT_VERSION,
                type="job.updated",
                event_id=event.event_id,
                job=job_to_wire(event.job),
            )
        case BatchOffered():
            return m.BatchOffer(
                v=CONTRACT_VERSION,
                type="batch.offer",
                event_id=event.event_id,
                batch=write_batch_to_wire(event.batch),
            )
        case DiffProposed():
            return m.DiffProposed(
                v=CONTRACT_VERSION,
                type="diff.proposed",
                event_id=event.event_id,
                diff=tree_diff_to_wire(event.diff),
            )
