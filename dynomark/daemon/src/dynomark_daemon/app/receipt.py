"""Use case: a receipt is processed (DYNOMARK.DESIGN.md, Behaviors and
Interfaces; The daemon, "Receipts"; contract/v1 README, Jobs: Receipt -> job,
and Write batches: Receipts, Inverses).

The first receipt recorded for a batch wins; a repeat records nothing new,
but finishes what a daemon stopped mid-receipt left undone for a job still
waiting on the batch. A receipt acknowledges the batch's offer, so the next
batch can be offered.
"""

from dataclasses import dataclass

from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.app.file import propose_inverse
from dynomark_daemon.app.jobs import record_job_change
from dynomark_daemon.domain.batch import (
    BatchReceipt,
    BatchRecord,
    ReceiptApplied,
    ReceiptRejected,
    WriteBatch,
    applied_ops,
    filing_failure,
    invert,
)
from dynomark_daemon.domain.events import BatchOffered
from dynomark_daemon.domain.ids import SnapshotId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.tree import OwnedRoots
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.store import CorpusStorePort


@dataclass(frozen=True, slots=True)
class ReceiptRecorded:
    """What a receipt did: ``first`` is false for a repeat, which changed
    nothing; ``job`` is the batch's job as it now stands; ``inverse`` the
    batch offered back for the applied prefix, if any."""

    first: bool
    job: Job | None
    inverse: WriteBatch | None


def _archive(
    receipt: BatchReceipt, record: BatchRecord, *, store: CorpusStorePort
) -> SnapshotId | None:
    """The batch's fallback export: the receipt's snapshot when it was read
    before any op of the batch changed the tree, else the one kept at offer."""
    if not receipt.pre_batch or receipt.snapshot is None:
        return record.snapshot_id
    snapshot_id = SnapshotId(f"receipt-{record.batch.batch_id}")
    store.put_snapshot(snapshot_id, receipt.snapshot)
    return snapshot_id


def _acknowledge_offer(record: BatchRecord, *, store: CorpusStorePort) -> None:
    offers = [
        p.event.event_id
        for p in store.unacked_events(record.profile_id)
        if isinstance(p.event, BatchOffered)
        and p.event.batch.batch_id == record.batch.batch_id
    ]
    store.ack_events(record.profile_id, offers)


def _needs_inverse(receipt: BatchReceipt, failure: str | None) -> bool:
    if isinstance(receipt, ReceiptRejected):
        return False
    return not isinstance(receipt, ReceiptApplied) or failure is not None


def _awaits(job: Job | None, record: BatchRecord) -> bool:
    """The job still waits on this batch's receipt."""
    return (
        job is not None
        and job.state is JobState.PLACED
        and job.batch_id == record.batch.batch_id
    )


def receive_receipt(
    receipt: BatchReceipt,
    roots: OwnedRoots,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> ReceiptRecorded:
    """Record the extension's answer for a batch, once.

    The steps after the batch row -- the offer's ack, the prefix inverse,
    the job change -- are finished by a repeat of the receipt when a daemon
    stopped between them: a repeat whose job still waits on this batch
    completes them from the receipt recorded first.

    Raises:
        UnknownRecord: no batch has ``receipt.batch_id`` (``not_found``).
    """
    record = store.get_batch(receipt.batch_id)
    if record is None:
        raise UnknownRecord(f"no batch {receipt.batch_id}")
    job = None if record.job_id is None else store.get_job(record.job_id)
    first = record.receipt is None
    recorded = record.receipt
    if recorded is None:
        record = record.with_receipt(receipt, _archive(receipt, record, store=store))
        store.put_batch(record)
        recorded = receipt
    elif not _awaits(job, record):
        return ReceiptRecorded(first=False, job=job, inverse=None)
    _acknowledge_offer(record, store=store)
    failure = filing_failure(
        record.batch, recorded, job.node_id if job is not None else None
    )
    inverse = None
    tree = recorded.snapshot or store.latest_tree_snapshot()
    if (
        _needs_inverse(recorded, failure)
        and record.undone_by is None
        and tree is not None
    ):
        operations = invert(record.batch, applied_ops(recorded), tree, roots)
        if operations:
            inverse = propose_inverse(
                record, operations, roots, store=store, clock=clock, ids=ids
            )
    if job is not None and _awaits(job, record):
        now = clock.now_ms()
        job = job.filed(at=now) if failure is None else job.failed(failure, at=now)
        record_job_change(job, store=store, ids=ids)
    return ReceiptRecorded(first=first, job=job, inverse=inverse)
