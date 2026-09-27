"""Use case: a batch is undone (DYNOMARK.DESIGN.md, Behaviors and Interfaces;
The daemon, "Undo"; Goal 6; contract/v1 README, Undo guard and the
idempotency table).
"""

from dataclasses import dataclass

from dynomark_daemon.app.errors import Busy, InvalidRequest, UnknownRecord
from dynomark_daemon.app.file import propose_inverse
from dynomark_daemon.app.flags import locked_folders
from dynomark_daemon.domain.batch import (
    BatchState,
    UndoDrop,
    WriteBatch,
    applied_ops,
    guarded_inverse,
)
from dynomark_daemon.domain.ids import BatchId
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import OwnedRoots
from dynomark_daemon.domain.writer import WriterConflict
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.store import CorpusStorePort


@dataclass(frozen=True, slots=True)
class Undone:
    """The inverse ``batch`` of ``undoes`` (``None`` when the guard dropped
    every step) and the steps it dropped."""

    undoes: BatchId
    batch: WriteBatch | None
    dropped: tuple[UndoDrop, ...]


def undo(
    batch_id: BatchId,
    role: HostRole,
    roots: OwnedRoots,
    *,
    conflict: WriterConflict | None = None,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> Undone | NotWriter | WriterConflict:
    """The guarded inverse of an ``APPLIED`` batch, stored and offered once;
    a writer in ``conflict`` refuses. One unit of work: the check that no
    inverse is recorded and the inverse's creation cannot interleave with
    another undo, and a crash leaves either both or neither.

    Raises:
        UnknownRecord: no such batch (``not_found``).
        InvalidRequest: the batch is not ``APPLIED`` (``invalid``).
        Busy: no tree snapshot recorded since its receipt (``busy``).
    """
    if role is HostRole.READER:
        return NotWriter(use_case="undo")
    if conflict is not None:
        return conflict
    with store.atomic():
        return _undo(batch_id, roots, store=store, clock=clock, ids=ids)


def _undo(
    batch_id: BatchId,
    roots: OwnedRoots,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> Undone:
    record = store.get_batch(batch_id)
    if record is None:
        raise UnknownRecord(f"no batch {batch_id}")
    if record.undone_by is not None:
        inverse = store.get_batch(record.undone_by)
        if inverse is None:
            raise UnknownRecord(f"no batch {record.undone_by}")
        return Undone(undoes=batch_id, batch=inverse.batch, dropped=inverse.report)
    if record.state is not BatchState.APPLIED or record.receipt is None:
        raise InvalidRequest(f"batch {batch_id} is {record.state.value}, not APPLIED")
    tree = store.latest_tree_snapshot()
    if not record.tree_since_receipt or tree is None:
        raise Busy(f"no tree snapshot since the receipt of {batch_id}")
    operations, dropped = guarded_inverse(
        record.batch,
        applied_ops(record.receipt),
        tree,
        roots,
        locked=locked_folders(store=store),
    )
    if not operations:
        return Undone(undoes=batch_id, batch=None, dropped=dropped)
    batch = propose_inverse(
        record, operations, roots, report=dropped, store=store, clock=clock, ids=ids
    )
    return Undone(undoes=batch_id, batch=batch, dropped=dropped)
