"""Use case: a placement becomes a batch (DYNOMARK.DESIGN.md, Behaviors and
Interfaces; The daemon, "Place and file"; Goal 8).

The batch's move consumes the ``Follow Up`` node. The boundary policy runs
before anything is stored; the batch is stored ``PROPOSED`` and offered
(a ``batch.offer`` event in the outbox), and the job points at it.
"""

from dataclasses import replace

from dynomark_daemon.app.errors import TreeNotReady, UnknownRecord
from dynomark_daemon.domain.batch import (
    BatchRecord,
    BatchState,
    Expect,
    Operation,
    UndoDrop,
    WriteBatch,
    admit,
    filing_operations,
    parking_operations,
    plan_inverse,
)
from dynomark_daemon.domain.events import BatchOffered
from dynomark_daemon.domain.ids import BatchId, EventId, SnapshotId
from dynomark_daemon.domain.job import Job
from dynomark_daemon.domain.placement import Placement
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import OwnedRoots, TreeOutline
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.store import CorpusStorePort


def saved_node_expect(job: Job, *, store: CorpusStorePort) -> Expect:
    """Where the job's node was saved, as the precondition its move re-checks.

    Raises:
        TreeNotReady: no tree snapshot resolves the folder it was saved in.
    """
    save = store.get_save(job.job_id)
    if save is None:
        raise UnknownRecord(f"job {job.job_id} has no save")
    tree = store.latest_tree_snapshot()
    parent_id = None if tree is None else tree.resolve(save.bookmark.path)
    if parent_id is None:
        raise TreeNotReady(f"no tree snapshot resolves {save.bookmark.path.names}")
    return Expect(parent_id=parent_id, parent_path=save.bookmark.path)


def offer(record: BatchRecord, *, store: CorpusStorePort, ids: IdSource) -> WriteBatch:
    """Store ``record`` and its ``batch.offer`` event (the outbox), in one unit
    of work; the batch also keeps the latest tree as its fallback export
    until a receipt brings the pre-batch one."""
    with store.atomic():
        tree = store.latest_tree_snapshot()
        if tree is not None and record.snapshot_id is None:
            snapshot_id = SnapshotId(f"tree-{tree.taken_at}")
            store.put_snapshot(snapshot_id, tree)
            record = replace(record, snapshot_id=snapshot_id)
        store.put_batch(record)
        event = BatchOffered(event_id=EventId(ids.new_id("event")), batch=record.batch)
        store.put_event(record.profile_id, event)
    return record.batch


def propose_inverse(
    original: BatchRecord,
    operations: tuple[Operation, ...],
    roots: OwnedRoots,
    *,
    report: tuple[UndoDrop, ...] = (),
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> WriteBatch:
    """Store and offer ``operations`` as the one recorded inverse of
    ``original``, and link it as ``original.undone_by``, in one unit of
    work: callers make an inverse only while ``undone_by`` is unset, so an
    offered inverse without that link would be offered again. It carries
    the original's ``DiffItem`` reference."""
    if original.batch.diff_item_id is None:
        admit(operations, roots)
    batch = WriteBatch(
        batch_id=BatchId(ids.new_id("batch")),
        operations=operations,
        inverse=plan_inverse(operations, roots),
        diff_item_id=original.batch.diff_item_id,
    )
    record = BatchRecord(
        batch=batch,
        state=BatchState.PROPOSED,
        created_at=clock.now_ms(),
        profile_id=original.profile_id,
        undoes=original.batch.batch_id,
        report=report,
    )
    with store.atomic():
        offered = offer(record, store=store, ids=ids)
        store.put_batch(replace(original, undone_by=batch.batch_id))
    return offered


def propose(
    operations: tuple[Operation, ...],
    job: Job,
    roots: OwnedRoots,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> WriteBatch:
    """Admit ``operations`` through the boundary, then store the job's batch
    ``PROPOSED``, offer it, and point the job at it.

    Raises:
        OutsideOwnedRoots: before anything is stored.
    """
    admit(operations, roots)
    now = clock.now_ms()
    batch = WriteBatch(
        batch_id=BatchId(ids.new_id("batch")),
        operations=operations,
        inverse=plan_inverse(operations, roots),
    )
    record = BatchRecord(
        batch=batch,
        state=BatchState.PROPOSED,
        created_at=now,
        profile_id=job.profile_id,
        job_id=job.job_id,
        identity=job.identity,
    )
    offer(record, store=store, ids=ids)
    store.put_job(job.filed_by(batch.batch_id, at=now))
    return batch


def file(
    placement: Placement,
    job: Job,
    outline: TreeOutline,
    roots: OwnedRoots,
    role: HostRole,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> WriteBatch | NotWriter:
    """Turn ``placement`` of ``job``'s node into a stored, offered batch.

    Raises:
        OutsideOwnedRoots: the placement leaves the owned roots.
        TreeNotReady: no tree snapshot resolves where the node was saved.
    """
    if role is HostRole.READER:
        return NotWriter(use_case="file")
    operations = filing_operations(
        placement.folder,
        outline,
        node_id=job.node_id,
        expect=saved_node_expect(job, store=store),
    )
    return propose(operations, job, roots, store=store, clock=clock, ids=ids)


def park(
    job: Job,
    roots: OwnedRoots,
    role: HostRole,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> WriteBatch | NotWriter:
    """File nothing new for a duplicate identity: a batch moves ``job``'s node
    to ``Graveyard``; the existing placement is untouched.

    Raises:
        TreeNotReady: no tree snapshot resolves where the node was saved.
    """
    if role is HostRole.READER:
        return NotWriter(use_case="park")
    operations = parking_operations(
        roots, node_id=job.node_id, expect=saved_node_expect(job, store=store)
    )
    return propose(operations, job, roots, store=store, clock=clock, ids=ids)
