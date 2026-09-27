"""The bookmark tree as the daemon sees it: paths, owned roots, outline, snapshot."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from dynomark_daemon.domain.ids import NodeId

WRITER_MARKER_PREFIX: Final = "dynomark-writer:"
"""The title prefix of a writer's marker folder (contract v1, Writer marker)."""


class RootKey(StrEnum):
    """A browser top-level folder a ``FolderPath`` starts from."""

    BAR = "bar"
    OTHER = "other"
    MOBILE = "mobile"
    MENU = "menu"


class NodeKind(StrEnum):
    FOLDER = "folder"
    BOOKMARK = "bookmark"
    SEPARATOR = "separator"


@dataclass(frozen=True, slots=True)
class FolderPath:
    """Ordered folder names from a root; ``names == ()`` is the root itself."""

    root: RootKey
    names: tuple[str, ...]

    def is_inside(self, other: "FolderPath") -> bool:
        """``other`` is this path or one of its ancestors (a syntactic test)."""
        return self.root == other.root and self.names[: len(other.names)] == other.names

    def child(self, name: str) -> "FolderPath":
        return FolderPath(root=self.root, names=(*self.names, name))

    def prefix(self, depth: int) -> "FolderPath":
        """The ancestor-or-self holding the first ``depth`` names."""
        return FolderPath(root=self.root, names=self.names[:depth])


@dataclass(frozen=True, slots=True)
class OwnedRoots:
    """The three folders Dynomark owns; a value handed to the boundary policy."""

    follow_up: FolderPath
    dynomark: FolderPath
    graveyard: FolderPath

    def all(self) -> tuple[FolderPath, FolderPath, FolderPath]:
        return (self.follow_up, self.dynomark, self.graveyard)

    def contains(self, path: FolderPath) -> bool:
        """``path`` is an owned root or lies inside one (contract v1, Boundary:
        a syntactic test on paths)."""
        return any(path.is_inside(root) for root in self.all())

    def is_root(self, path: FolderPath) -> bool:
        return path in self.all()


@dataclass(frozen=True, slots=True)
class FolderFlags:
    """``pinned``: immune to rebuild and audit moves. ``locked``: never a
    placement candidate, never moved, renamed or merged by any batch."""

    pinned: bool
    locked: bool


@dataclass(frozen=True, slots=True)
class OutlineFolder:
    """One folder of the owned subtree: flags and item count, no URLs."""

    node_id: NodeId
    path: FolderPath
    pinned: bool
    locked: bool
    item_count: int


@dataclass(frozen=True, slots=True)
class TreeOutline:
    """The folder skeleton of the ``Dynomark`` subtree rooted at ``root``."""

    root: FolderPath
    folders: tuple[OutlineFolder, ...]

    def folder_at(self, path: FolderPath) -> OutlineFolder | None:
        return next((f for f in self.folders if f.path == path), None)

    def children_of(self, path: FolderPath) -> tuple[OutlineFolder, ...]:
        depth = len(path.names) + 1
        return tuple(
            f
            for f in self.folders
            if len(f.path.names) == depth and f.path.is_inside(path)
        )

    def is_locked(self, path: FolderPath) -> bool:
        """``path`` is a locked folder or lies inside one."""
        return any(f.locked and path.is_inside(f.path) for f in self.folders)


@dataclass(frozen=True, slots=True)
class RootIds:
    """The node each ``RootKey`` maps to in one snapshot."""

    bar: NodeId
    other: NodeId
    mobile: NodeId | None = None
    menu: NodeId | None = None


@dataclass(frozen=True, slots=True)
class SnapshotNode:
    """One node of a ``Snapshot``; only a bookmark carries a url."""

    node_id: NodeId
    parent_id: NodeId | None
    index: int
    kind: NodeKind
    title: str
    date_added: int
    url: str | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The full tree as the extension read it at ``taken_at`` (epoch ms)."""

    taken_at: int
    root_ids: RootIds
    nodes: tuple[SnapshotNode, ...]

    def node(self, node_id: NodeId) -> SnapshotNode | None:
        return next((n for n in self.nodes if n.node_id == node_id), None)

    def children(self, node_id: NodeId) -> list[SnapshotNode]:
        """The node's children by index."""
        found = [n for n in self.nodes if n.parent_id == node_id]
        return sorted(found, key=lambda n: n.index)

    def path_of(self, folder_id: NodeId) -> FolderPath | None:
        """The path of a folder: titles up to the root node it hangs from."""
        roots = {
            getattr(self.root_ids, key.value): key
            for key in RootKey
            if getattr(self.root_ids, key.value) is not None
        }
        names: list[str] = []
        current = self.node(folder_id)
        while current is not None and current.node_id not in roots:
            names.append(current.title)
            current = (
                None if current.parent_id is None else self.node(current.parent_id)
            )
        if current is None:
            return None
        return FolderPath(root=roots[current.node_id], names=tuple(reversed(names)))

    def resolve(self, path: FolderPath) -> NodeId | None:
        """The folder ``path`` names (contract v1, Write batches, Paths): from
        the root's node, at each level the child folder with the lowest index
        whose title equals the name exactly."""
        current: NodeId | None = getattr(self.root_ids, path.root.value)
        for name in path.names:
            if current is None:
                return None
            current = next(
                (
                    child.node_id
                    for child in self.children(current)
                    if child.kind is NodeKind.FOLDER and child.title == name
                ),
                None,
            )
        return current


# --- The outline of the Dynomark subtree ---


def _outline_folders(
    snapshot: Snapshot,
    node_id: NodeId,
    path: FolderPath,
    flags: Mapping[NodeId, FolderFlags],
) -> list[OutlineFolder]:
    children = snapshot.children(node_id)
    own = flags.get(node_id, FolderFlags(pinned=False, locked=False))
    folder = OutlineFolder(
        node_id=node_id,
        path=path,
        pinned=own.pinned,
        locked=own.locked,
        item_count=sum(child.kind is NodeKind.BOOKMARK for child in children),
    )
    below = [
        found
        for child in children
        if child.kind is NodeKind.FOLDER
        and not child.title.startswith(WRITER_MARKER_PREFIX)
        for found in _outline_folders(
            snapshot, child.node_id, path.child(child.title), flags
        )
    ]
    return [folder, *below]


def outline_of(
    snapshot: Snapshot, root: FolderPath, flags: Mapping[NodeId, FolderFlags]
) -> TreeOutline:
    """The ``TreeOutline`` of the subtree ``root`` resolves to in ``snapshot``:
    every folder but writer markers, with its flags and bookmark count;
    empty when ``root`` does not resolve."""
    root_id = snapshot.resolve(root)
    if root_id is None:
        return TreeOutline(root=root, folders=())
    return TreeOutline(
        root=root, folders=tuple(_outline_folders(snapshot, root_id, root, flags))
    )
