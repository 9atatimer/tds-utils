"""A saved bookmark, its capture, and the corpus entry built from them."""

from dataclasses import dataclass
from enum import StrEnum

from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.tree import FolderPath


@dataclass(frozen=True, slots=True)
class Identity:
    """The normalized URL: the cross-host identity of a bookmark.

    Computed on the daemon only; the extension sends the raw URL.
    """

    value: str


@dataclass(frozen=True, slots=True)
class Bookmark:
    """A raw URL plus title at a ``FolderPath``, with its per-profile ``NodeId``."""

    node_id: NodeId
    url: str
    title: str
    path: FolderPath
    date_added: int


class CaptureSource(StrEnum):
    TAB = "tab"
    BACKGROUND_TAB = "background_tab"
    FETCH = "fetch"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Capture:
    """Readable text plus title for a bookmark, and where it came from."""

    source: CaptureSource
    text: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class Embedding:
    """A vector plus the id of the model that produced it."""

    vector: tuple[float, ...]
    model_id: str


@dataclass(frozen=True, slots=True)
class Enrichment:
    """What the completion model returns for a capture: summary and tags."""

    summary: str
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    """A bookmark plus capture, summary, tags and embedding."""

    identity: Identity
    bookmark: Bookmark
    capture: Capture
    summary: str
    tags: tuple[str, ...]
    embedding: Embedding
    indexed_at: int
