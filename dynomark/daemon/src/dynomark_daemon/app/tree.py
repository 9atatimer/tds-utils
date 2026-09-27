"""Use case: a tree snapshot is recorded (contract/v1 README, Connection
lifecycle: the extension sends ``tree.snapshot`` after every hello, after
every receipt result, and after owned-root changes).

The latest tree resolves the parent ids a batch's ``Expect`` names, finds
duplicates, feeds the outline, and runs the undo guard.
"""

from dataclasses import replace

from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import Snapshot
from dynomark_daemon.ports.store import CorpusStorePort


def record_tree_snapshot(
    snapshot: Snapshot, role: HostRole, *, store: CorpusStorePort
) -> None:
    """Keep ``snapshot`` as the latest tree (unless a later one is kept) and
    ready the undo guard of every batch whose receipt came before it.

    A reader's snapshot is not kept: node ids are per profile, and only the
    writer's profile has batches (see the contract defect in the report).
    """
    if role is HostRole.READER:
        return
    store.put_tree_snapshot(snapshot)
    if store.latest_tree_snapshot() != snapshot:
        return
    for record in store.list_batches():
        if record.receipt is not None and not record.tree_since_receipt:
            store.put_batch(replace(record, tree_since_receipt=True))
