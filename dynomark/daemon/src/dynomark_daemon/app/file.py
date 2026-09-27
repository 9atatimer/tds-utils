"""Use case: a placement becomes a batch (DYNOMARK.DESIGN.md, Behaviors and
Interfaces; The daemon, "Place and file"; Goal 8).

The batch's move consumes the ``Follow Up`` node. The boundary policy runs
before anything is stored; the batch is stored ``PROPOSED`` and offered
(a ``batch.offer`` event in the outbox), and the job points at it.
"""

from dynomark_daemon.app.errors import TreeNotReady, UnknownRecord
from dynomark_daemon.domain.batch import (
    BatchRecord,
    BatchState,
    Expect,
    Operation,
    WriteBatch,
    admit,
    filing_operations,
    plan_inverse,
)
from dynomark_daemon.domain.events import BatchOffered
from dynomark_daemon.domain.ids import BatchId, EventId
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
    store.put_batch(
        BatchRecord(
            batch=batch,
            state=BatchState.PROPOSED,
            created_at=now,
            profile_id=job.profile_id,
            job_id=job.job_id,
            identity=job.identity,
        )
    )
    offer = BatchOffered(event_id=EventId(ids.new_id("event")), batch=batch)
    store.put_event(job.profile_id, offer)
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
    operations = filing_operations(
        placement.folder,
        outline,
        node_id=job.node_id,
        expect=saved_node_expect(job, store=store),
    )
    return propose(operations, job, roots, store=store, clock=clock, ids=ids)
