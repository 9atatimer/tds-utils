"""Behaviors row: a tree snapshot is recorded (contract/v1 README, Connection
lifecycle: ``tree.snapshot`` after every hello and every receipt; Undo
guard) -- and its cost does not grow with the filings on record.

Both use cases a ``tree.snapshot`` runs on the lane, ``record_tree_snapshot``
and ``ensure_writer_marker``, read only the batches they act on: the
receipted batches not yet re-snapshotted, and this profile's PROPOSED
batches. ``list_batches`` decodes every batch ever filed, so neither may
call it (a store here fails the test if they do).
"""

from dataclasses import replace

from dynomark_daemon.app.tree import record_tree_snapshot
from dynomark_daemon.app.writer import ensure_writer_marker
from dynomark_daemon.domain.batch import (
    BatchRecord,
    BatchState,
    OpApplied,
    ReceiptApplied,
    WriteBatch,
)
from dynomark_daemon.domain.ids import BatchId, HostId, NodeId, ProfileId
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_batch, make_node, make_roots, make_tree

A = ProfileId("profile-a")
MBP = HostId("mbp")
FRESH = make_tree(make_node("10", "1", "Follow Up"))
LATER = make_tree(make_node("10", "1", "Follow Up"), taken_at=FRESH.taken_at + 1)


class _NoScanStore(InMemoryCorpusStore):
    """A store on which reading every batch fails the test."""

    def list_batches(self) -> list[BatchRecord]:
        raise AssertionError("a tree.snapshot use case read every batch")


def _receipted(batch_id: str) -> BatchRecord:
    record = make_batch(batch_id, profile_id=A)
    receipt = ReceiptApplied(
        batch_id=BatchId(batch_id),
        applied=(OpApplied(index=0, node_id=NodeId("42"), changed=True),),
        skipped=(),
        pre_batch=True,
        snapshot=FRESH,
    )
    return record.with_receipt(receipt, None)


def _ensure(store: InMemoryCorpusStore) -> WriteBatch | None:
    return ensure_writer_marker(
        HostRole.WRITER,
        MBP,
        make_roots(),
        A,
        store=store,
        clock=FakeClock(start_ms=1_000),
        ids=SequentialIds(),
    )


def test_a_snapshot_readies_the_receipted_batches_without_reading_every_batch() -> None:
    """Given a receipted batch, one already re-snapshotted and one still
    PROPOSED, When a newer tree is recorded, Then the receipted batch is
    ready for the undo guard, the others are unchanged, and no use case read
    every batch."""
    store = _NoScanStore()
    store.put_batch(fresh := _receipted("batch-fresh"))
    store.put_batch(done := replace(_receipted("batch-done"), tree_since_receipt=True))
    store.put_batch(pending := make_batch("batch-pending", profile_id=A))

    record_tree_snapshot(LATER, HostRole.WRITER, store=store)

    assert store.get_batch(fresh.batch.batch_id) == replace(
        fresh, tree_since_receipt=True
    )
    assert store.get_batch(done.batch.batch_id) == done
    assert store.get_batch(pending.batch.batch_id) == pending


def test_a_pending_marker_batch_is_found_without_reading_every_batch() -> None:
    """Given a tree with no marker, When the writer's marker is ensured twice,
    Then the first offers the marker batch and the second, seeing it still
    PROPOSED, offers nothing -- and neither read every batch."""
    store = _NoScanStore()
    store.put_batch(_receipted("batch-old"))
    store.put_tree_snapshot(FRESH)

    first, second = _ensure(store), _ensure(store)

    assert first is not None
    assert second is None
    marker = store.get_batch(first.batch_id)
    assert marker is not None and marker.state is BatchState.PROPOSED
