"""Use case: a tree snapshot is recorded (contract/v2 README, Connection
lifecycle: the extension sends ``tree.snapshot`` after every hello, after
every receipt result, and after owned-root changes).

The latest tree resolves the parent ids a batch's ``Expect`` names, finds
duplicates, feeds the outline, and runs the undo guard.
"""

from dataclasses import replace

from dynomark_daemon.domain.ids import ProfileId
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import Snapshot
from dynomark_daemon.ports.store import CorpusStorePort


def record_tree_snapshot(
    snapshot: Snapshot, role: HostRole, profile: ProfileId, *, store: CorpusStorePort
) -> None:
    """Keep ``snapshot`` as the latest tree (unless a later one is kept) and
    ready the undo guard of every batch whose receipt came before it.

    A connection served reader keeps it as its profile's tree, for Retention
    only (issue #421): node ids are per profile and only the writer's
    profile has batches, so it never becomes the latest tree.
    """
    if role is HostRole.READER:
        store.put_profile_tree(profile, snapshot)
        return
    # No unit of work: a kill part-way leaves ``tree.snapshot`` unanswered and
    # its re-send (same ``taken_at``) is kept again as the latest, so the
    # loop below runs again over every batch still not marked; every later
    # snapshot does the same. Only those batches are read: this runs on the
    # lane after every receipt, so its cost must not grow with the filings.
    store.put_tree_snapshot(snapshot)
    if store.latest_tree_snapshot() != snapshot:
        return
    for record in store.batches_awaiting_tree():
        store.put_batch(replace(record, tree_since_receipt=True))
