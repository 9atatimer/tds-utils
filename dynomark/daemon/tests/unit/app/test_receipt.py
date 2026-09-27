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
from dynomark_daemon.app.receipt import ReceiptRecorded
from dynomark_daemon.domain.batch import (
    BatchState,
    Expect,
    FailReason,
    OpCreateFolder,
    OpFailed,
    OpRemove,
    OpSkipped,
    ReceiptApplied,
    ReceiptPartial,
    ReceiptRejected,
    RejectReason,
    SkipReason,
)
from dynomark_daemon.domain.events import JobUpdated
from dynomark_daemon.domain.ids import BatchId, NodeId
from dynomark_daemon.domain.job import JobState
from tests._factories import make_path
from tests.unit.app._filed import CREATED, MOVED, RUST, TREE, Daemon


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


CREATE_GRAVEYARD = OpCreateFolder(index=0, parent=make_path(), title="Graveyard")
REMOVE_CREATED = OpRemove(
    index=1,
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
    assert recorded.inverse.operations == (CREATE_GRAVEYARD, REMOVE_CREATED)
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
    assert recorded.inverse.operations == (CREATE_GRAVEYARD, REMOVE_CREATED)


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
