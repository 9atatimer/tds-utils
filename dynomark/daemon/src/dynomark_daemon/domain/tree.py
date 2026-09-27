"""The bookmark tree as the daemon sees it: paths, owned roots, outline, snapshot."""

from dataclasses import dataclass
from enum import StrEnum

from dynomark_daemon.domain.ids import NodeId


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


@dataclass(frozen=True, slots=True)
class OwnedRoots:
    """The three folders Dynomark owns; a value handed to the boundary policy."""

    follow_up: FolderPath
    dynomark: FolderPath
    graveyard: FolderPath


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
    """The folder skeleton of the owned subtree."""

    folders: tuple[OutlineFolder, ...]


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
