"""Use case: a receipt is processed (DYNOMARK.DESIGN.md, Behaviors and
Interfaces; The daemon, "Receipts"; contract/v1 README, Jobs: Receipt -> job,
and Write batches: Receipts, Inverses).

The first receipt recorded for a batch wins; a repeat records nothing. A
receipt acknowledges the batch's offer, so the next batch can be offered.
"""

from dataclasses import dataclass

from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.app.file import propose_inverse
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
from dynomark_daemon.domain.events import BatchOffered, JobUpdated
from dynomark_daemon.domain.ids import EventId, SnapshotId
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


def receive_receipt(
    receipt: BatchReceipt,
    roots: OwnedRoots,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> ReceiptRecorded:
    """Record the extension's answer for a batch, once.

    Raises:
        UnknownRecord: no batch has ``receipt.batch_id`` (``not_found``).
    """
    record = store.get_batch(receipt.batch_id)
    if record is None:
        raise UnknownRecord(f"no batch {receipt.batch_id}")
    job = None if record.job_id is None else store.get_job(record.job_id)
    if record.receipt is not None:
        return ReceiptRecorded(first=False, job=job, inverse=None)
    record = record.with_receipt(receipt, _archive(receipt, record, store=store))
    store.put_batch(record)
    _acknowledge_offer(record, store=store)
    failure = filing_failure(
        record.batch, receipt, job.node_id if job is not None else None
    )
    inverse = None
    tree = receipt.snapshot or store.latest_tree_snapshot()
    if _needs_inverse(receipt, failure) and tree is not None:
        operations = invert(record.batch, applied_ops(receipt), tree, roots)
        if operations:
            inverse = propose_inverse(
                record, operations, roots, store=store, clock=clock, ids=ids
            )
    if (
        job is not None
        and job.state is JobState.PLACED
        and job.batch_id == record.batch.batch_id
    ):
        now = clock.now_ms()
        job = job.filed(at=now) if failure is None else job.failed(failure, at=now)
        store.put_job(job)
        store.put_event(
            job.profile_id, JobUpdated(event_id=EventId(ids.new_id("event")), job=job)
        )
    return ReceiptRecorded(first=True, job=job, inverse=inverse)
