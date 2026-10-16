"""Use case: an owned folder is pinned or locked (DYNOMARK.DESIGN.md, glossary
``pinned`` and ``locked``; Behaviors "Placement respects a lock";
contract/v1 ``folder.flags.set``).

The request names a folder by this host's node id; the flags are kept by
the folder's path, which every writer's tree resolves alike, so a writer
change keeps every pin and lock (issue #423). They are read into every
``TreeOutline`` (placement skips a locked folder, diffs never move a pinned
one).
"""

from dynomark_daemon.app.errors import InvalidRequest, TreeNotReady, UnknownRecord
from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import (
    FolderFlags,
    FolderPath,
    NodeKind,
    OutlineFolder,
    OwnedRoots,
    Snapshot,
)
from dynomark_daemon.domain.writer import WriterConflict
from dynomark_daemon.ports.store import CorpusStorePort

UNFLAGGED = FolderFlags(pinned=False, locked=False)


def set_folder_flags(
    node_id: NodeId,
    path: FolderPath | None,
    pinned: bool | None,
    locked: bool | None,
    role: HostRole,
    roots: OwnedRoots,
    *,
    conflict: WriterConflict | None = None,
    store: CorpusStorePort,
) -> OutlineFolder | NotWriter | WriterConflict:
    """Set the flags given (``None`` keeps one) on the owned folder
    ``node_id``; ``path``, when given, must be where it is. A writer in
    ``conflict`` refuses.

    Raises:
        TreeNotReady: no tree snapshot yet (``busy``).
        UnknownRecord: no such folder, or it is not at ``path``
            (``not_found``).
        InvalidRequest: the folder is outside the owned roots (``invalid``).
    """
    if role is HostRole.READER:
        return NotWriter(use_case="set_folder_flags")
    if conflict is not None:
        return conflict
    tree = store.latest_tree_snapshot()
    if tree is None:
        raise TreeNotReady("no tree snapshot to find the folder in")
    node = tree.node(node_id)
    where = tree.path_of(node_id) if node is not None else None
    if node is None or node.kind is not NodeKind.FOLDER or where is None:
        raise UnknownRecord(f"no folder {node_id}")
    if path is not None and path != where:
        raise UnknownRecord(f"folder {node_id} is not at {list(path.names)}")
    if not roots.contains(where):
        raise InvalidRequest(f"{list(where.names)} is not an owned folder")
    now = store.folder_flags().get(where, UNFLAGGED)
    flags = FolderFlags(
        pinned=now.pinned if pinned is None else pinned,
        locked=now.locked if locked is None else locked,
    )
    if flags != now:
        store.put_folder_flags(where, flags)
    count = sum(c.kind is NodeKind.BOOKMARK for c in tree.children(node_id))
    return OutlineFolder(
        node_id=node_id,
        path=where,
        pinned=flags.pinned,
        locked=flags.locked,
        item_count=count,
    )


def locked_folders(tree: Snapshot, *, store: CorpusStorePort) -> frozenset[NodeId]:
    """The folders of ``tree`` no batch may move (Glossary: ``locked``): each
    locked path as ``tree`` resolves it."""
    locked = (path for path, flags in store.folder_flags().items() if flags.locked)
    resolved = (tree.resolve(path) for path in locked)
    return frozenset(node_id for node_id in resolved if node_id is not None)
