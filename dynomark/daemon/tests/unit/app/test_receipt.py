"""Behaviors row: A receipt is processed (DYNOMARK.DESIGN.md, Behaviors and
Interfaces; The daemon, "Receipts") -- ``receive_receipt(receipt, *, store)
-> Job or WriteBatch``: "Given APPLIED, Then the job is FILED and the
snapshot stored; Given PARTIAL, Then the job is FAILED and a PROPOSED
inverse of the prefix exists"; REJECTED -> FAILED (State Machine). With
contract v1's rows (Jobs, Receipt -> job): a skipped filing op fails the
job like PARTIAL, and a receipt delivered twice is recorded once
(``receipt.batch_id`` is the idempotency key; "A receipt is delivered").
"""

import pytest

from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.app.file import file
from dynomark_daemon.app.receipt import ReceiptRecorded, receive_receipt
from dynomark_daemon.domain.batch import (
    BatchReceipt,
    BatchState,
    Expect,
    FailReason,
    OpApplied,
    OpFailed,
    OpRemove,
    OpSkipped,
    ReceiptApplied,
    ReceiptPartial,
    ReceiptRejected,
    RejectReason,
    SkipReason,
    WriteBatch,
)
from dynomark_daemon.domain.bookmark import Save
from dynomark_daemon.domain.events import BatchOffered, JobUpdated
from dynomark_daemon.domain.ids import BatchId, NodeId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_bookmark,
    make_capture,
    make_job,
    make_node,
    make_outline,
    make_outline_folder,
    make_path,
    make_placement,
    make_roots,
    make_tree,
)

RUST = make_path("Dynomark", "Rust")
ASYNC = make_path("Dynomark", "Rust", "Async")
TREE = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("14", "11", "Rust"),
    make_node("42", "10", "Tokio tutorial", url="https://tokio.rs/tokio/tutorial"),
)
CREATED = OpApplied(index=0, node_id=NodeId("16"), changed=True)
MOVED = OpApplied(index=1, node_id=NodeId("42"), changed=True)


class Daemon:
    """A writer that has filed one job into a new folder, Dynomark/Rust/Async."""

    def __init__(self) -> None:
        self.store = InMemoryCorpusStore()
        self.clock, self.ids = FakeClock(start_ms=1_000), SequentialIds()
        self.job = make_job(state=JobState.PLACED)
        self.store.put_job(self.job)
        self.store.put_save(
            self.job.job_id,
            Save(
                bookmark=make_bookmark(path=make_path("Follow Up")),
                capture=make_capture(),
            ),
        )
        self.store.put_tree_snapshot(TREE)
        batch = file(
            make_placement(folder=ASYNC),
            self.job,
            make_outline(make_outline_folder("Dynomark", "Rust", node_id="14")),
            make_roots(),
            HostRole.WRITER,
            store=self.store,
            clock=self.clock,
            ids=self.ids,
        )
        assert isinstance(batch, WriteBatch)
        self.batch = batch

    def receive(self, receipt: BatchReceipt) -> ReceiptRecorded:
        return receive_receipt(
            receipt, make_roots(), store=self.store, clock=self.clock, ids=self.ids
        )

    def job_now(self) -> Job:
        job = self.store.get_job(self.job.job_id)
        assert job is not None
        return job

    def offers(self) -> list[BatchOffered]:
        pending = self.store.unacked_events(self.job.profile_id)
        return [p.event for p in pending if isinstance(p.event, BatchOffered)]


def _applied(daemon: Daemon, *, skipped: tuple[OpSkipped, ...] = ()) -> ReceiptApplied:
    applied = (CREATED,) if skipped else (CREATED, MOVED)
    return ReceiptApplied(
        batch_id=daemon.batch.batch_id,
        applied=applied,
        skipped=skipped,
        pre_batch=True,
        snapshot=TREE,
    )


def _partial(daemon: Daemon) -> ReceiptPartial:
    return ReceiptPartial(
        batch_id=daemon.batch.batch_id,
        applied=(CREATED,),
        skipped=(),
        failed=OpFailed(index=1, reason=FailReason.BROWSER_ERROR),
        pre_batch=True,
        snapshot=TREE,
    )


REMOVE_CREATED = OpRemove(
    index=0,
    node_id=NodeId("16"),
    expect=Expect(parent_id=NodeId("14"), parent_path=RUST, empty=True),
)


def test_receive_an_applied_receipt_files_the_job_and_stores_the_snapshot() -> None:
    """Given a PROPOSED filing batch, When its APPLIED receipt arrives, Then the
    job is FILED, the batch APPLIED with its receipt and snapshot stored, and
    the offer acknowledged."""
    daemon = Daemon()
    receipt = _applied(daemon)

    recorded = daemon.receive(receipt)

    assert recorded == ReceiptRecorded(first=True, job=daemon.job_now(), inverse=None)
    assert daemon.job_now().state is JobState.FILED
    record = daemon.store.get_batch(daemon.batch.batch_id)
    assert record is not None
    assert (record.state, record.receipt) == (BatchState.APPLIED, receipt)
    assert record.snapshot_id is not None
    assert daemon.store.get_snapshot(record.snapshot_id) == TREE
    assert daemon.offers() == []
    updates = [
        p.event.job
        for p in daemon.store.unacked_events(daemon.job.profile_id)
        if isinstance(p.event, JobUpdated)
    ]
    assert updates == [daemon.job_now()]


def test_receive_a_partial_receipt_fails_the_job_and_offers_the_prefix_inverse() -> (
    None
):
    """Given a filing batch whose move failed after its folder was created, When
    the PARTIAL receipt arrives, Then the job is FAILED and a PROPOSED inverse
    removing the created folder exists and is offered."""
    daemon = Daemon()

    recorded = daemon.receive(_partial(daemon))

    assert daemon.job_now().state is JobState.FAILED
    assert recorded.inverse is not None
    assert recorded.inverse.operations == (REMOVE_CREATED,)
    inverse = daemon.store.get_batch(recorded.inverse.batch_id)
    original = daemon.store.get_batch(daemon.batch.batch_id)
    assert inverse is not None and original is not None
    assert (inverse.state, inverse.undoes) == (
        BatchState.PROPOSED,
        original.batch.batch_id,
    )
    assert (original.state, original.undone_by) == (
        BatchState.PARTIAL,
        inverse.batch.batch_id,
    )
    assert [o.batch for o in daemon.offers()] == [inverse.batch]


def test_receive_an_applied_receipt_whose_filing_op_was_skipped_fails_the_job() -> None:
    """Given an APPLIED receipt that skipped the filing move (the node was moved
    away), When processed, Then the job is FAILED naming the skip, and the
    created folder is offered back as an inverse."""
    daemon = Daemon()
    skip = OpSkipped(index=1, reason=SkipReason.PARENT_MISMATCH)

    recorded = daemon.receive(_applied(daemon, skipped=(skip,)))

    job = daemon.job_now()
    assert job.state is JobState.FAILED
    assert job.last_error is not None and "parent_mismatch" in job.last_error
    assert recorded.inverse is not None
    assert recorded.inverse.operations == (REMOVE_CREATED,)


def test_receive_a_rejected_receipt_fails_the_job_with_no_inverse() -> None:
    """Given a REJECTED receipt, When processed, Then the job is FAILED and
    nothing is offered back (nothing was touched)."""
    daemon = Daemon()
    receipt = ReceiptRejected(
        batch_id=daemon.batch.batch_id,
        reason=RejectReason.BOUNDARY,
        pre_batch=True,
        snapshot=TREE,
    )

    recorded = daemon.receive(receipt)

    assert daemon.job_now().state is JobState.FAILED
    assert recorded.inverse is None
    record = daemon.store.get_batch(daemon.batch.batch_id)
    assert record is not None and record.state is BatchState.REJECTED
    assert daemon.offers() == []


def test_receive_a_receipt_twice_records_it_once() -> None:
    """Given a receipt already recorded, When it is delivered again, Then
    nothing new is recorded: no second inverse, no second job change."""
    daemon = Daemon()
    first = daemon.receive(_partial(daemon))
    events_after_first = daemon.store.unacked_events(daemon.job.profile_id)

    again = daemon.receive(_partial(daemon))

    assert (first.first, again.first) == (True, False)
    assert len(daemon.store.list_batches()) == 2
    assert daemon.store.unacked_events(daemon.job.profile_id) == events_after_first


def test_receive_a_receipt_for_an_unknown_batch_is_not_found() -> None:
    """Given no batch with the receipt's id, When it arrives, Then it raises
    UnknownRecord (error not_found)."""
    daemon = Daemon()
    receipt = ReceiptRejected(
        batch_id=BatchId("batch-unknown"),
        reason=RejectReason.INVALID,
        pre_batch=True,
        snapshot=TREE,
    )

    with pytest.raises(UnknownRecord):
        daemon.receive(receipt)
