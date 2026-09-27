"""Use cases: the writer keeps its marker; the writer's standing
(DYNOMARK.DESIGN.md, Key Decisions "Two writers"; contract/v1 README,
Writer marker and ``writer.status``).

The marker is created by an ordinary batch, offered on a writer connection
once its snapshot has no marker of this host, no other host's marker, and
no marker batch of this host is still unanswered.
"""

from dynomark_daemon.app.file import offer
from dynomark_daemon.domain.batch import (
    BatchRecord,
    BatchState,
    OpCreateFolder,
    WriteBatch,
    admit,
    plan_inverse,
)
from dynomark_daemon.domain.ids import BatchId, HostId, ProfileId
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import OwnedRoots
from dynomark_daemon.domain.writer import (
    WriterConflict,
    WriterStanding,
    marker_operations,
    marker_title,
    writer_standing,
)
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.store import CorpusStorePort


def writer_status(
    role: HostRole, host_id: HostId, roots: OwnedRoots, *, store: CorpusStorePort
) -> WriterStanding:
    """The standing of this host, served ``role``, in the latest tree."""
    return writer_standing(store.latest_tree_snapshot(), roots, host_id, role)


def writer_conflict(
    role: HostRole, host_id: HostId, roots: OwnedRoots, *, store: CorpusStorePort
) -> WriterConflict | None:
    """The conflict a writer is in, if any; a reader never is."""
    return writer_status(role, host_id, roots, store=store).refusal()


def _marker_pending(
    profile_id: ProfileId, title: str, *, store: CorpusStorePort
) -> bool:
    return any(
        record.state is BatchState.PROPOSED
        and record.profile_id == profile_id
        and any(
            isinstance(op, OpCreateFolder) and op.title == title
            for op in record.batch.operations
        )
        for record in store.list_batches()
    )


def ensure_writer_marker(
    role: HostRole,
    host_id: HostId,
    roots: OwnedRoots,
    profile_id: ProfileId,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> WriteBatch | None:
    """Offer the batch creating this host's marker when the latest tree lacks
    it; ``None`` when nothing is to be done (a reader, no tree, the marker
    present or pending, or another writer's marker seen)."""
    tree = store.latest_tree_snapshot()
    if role is HostRole.READER or tree is None:
        return None
    standing = writer_standing(tree, roots, host_id, role)
    title = marker_title(host_id)
    if (
        standing.own_marker
        or standing.conflict
        or _marker_pending(profile_id, title, store=store)
    ):
        return None
    operations = marker_operations(roots, host_id)
    admit(operations, roots)
    batch = WriteBatch(
        batch_id=BatchId(ids.new_id("batch")),
        operations=operations,
        inverse=plan_inverse(operations, roots),
    )
    record = BatchRecord(
        batch=batch,
        state=BatchState.PROPOSED,
        created_at=clock.now_ms(),
        profile_id=profile_id,
    )
    return offer(record, store=store, ids=ids)
