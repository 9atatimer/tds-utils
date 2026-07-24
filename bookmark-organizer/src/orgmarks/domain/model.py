"""Immutable in-memory bookmark model.

Everything here is a frozen, slotted dataclass -- the whole pipeline is a
pure transformation between values of these types. There is no database and
no persistent state between runs (beyond ``taxonomy.yml``, handled elsewhere).

A ``Bookmark.url`` is NEVER rewritten by orgmarks; canonicalization for
comparison happens in the normalizer and never mutates the stored value.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

RootName = Literal["bookmarks_bar", "other", "synced"]
ROOT_NAMES: tuple[RootName, ...] = ("bookmarks_bar", "other", "synced")

RuleSource = Literal["human", "learned"]
AssignmentVia = Literal["pin", "rule", "stay", "llm", "triage"]


@dataclass(frozen=True, slots=True)
class FolderPath:
    """A slash-free tuple of folder segments, e.g. ``work/dev`` -> (work, dev).

    The first segment is the root (an intent name or a Chrome root). An empty
    path is the tree root and is only used as a sentinel.
    """

    parts: tuple[str, ...] = ()

    @classmethod
    def from_string(cls, raw: str) -> FolderPath:
        """Parse ``a/b/c`` into a FolderPath, dropping empty segments."""
        return cls(tuple(seg for seg in raw.split("/") if seg))

    def __str__(self) -> str:
        return "/".join(self.parts)

    @property
    def name(self) -> str:
        """The last segment (empty string for the root)."""
        return self.parts[-1] if self.parts else ""

    @property
    def depth(self) -> int:
        """Number of segments."""
        return len(self.parts)

    @property
    def parent(self) -> FolderPath | None:
        """The path one level up, or None at depth 0 or 1."""
        if len(self.parts) <= 1:
            return None
        return FolderPath(self.parts[:-1])

    def child(self, name: str) -> FolderPath:
        """Return this path extended by one segment."""
        return FolderPath((*self.parts, name))

    def is_under(self, other: FolderPath) -> bool:
        """True if ``other`` is a prefix of (or equal to) this path."""
        return self.parts[: len(other.parts)] == other.parts


@dataclass(frozen=True, slots=True)
class Bookmark:
    """A single bookmark. ``url`` is authoritative and never rewritten."""

    url: str
    title: str
    add_date: int
    source_path: FolderPath
    guid: str | None = None


@dataclass(frozen=True, slots=True)
class Folder:
    """A folder node: subfolders and/or direct bookmarks, both ordered."""

    name: str
    subfolders: tuple[Folder, ...] = ()
    bookmarks: tuple[Bookmark, ...] = ()
    add_date: int | None = None

    @property
    def is_hub(self) -> bool:
        """A hub has subfolders."""
        return len(self.subfolders) > 0

    @property
    def is_leaf(self) -> bool:
        """A leaf has no subfolders."""
        return len(self.subfolders) == 0

    def iter_bookmarks(self) -> Iterator[Bookmark]:
        """Yield every bookmark in this folder and its descendants."""
        yield from self.bookmarks
        for sub in self.subfolders:
            yield from sub.iter_bookmarks()


@dataclass(frozen=True, slots=True)
class BookmarkTree:
    """The whole collection, keyed by Chrome root name."""

    roots: tuple[tuple[RootName, Folder], ...]

    def root(self, name: RootName) -> Folder:
        """Return the folder for a root name (empty Folder if absent)."""
        for root_name, folder in self.roots:
            if root_name == name:
                return folder
        return Folder(name=name)

    def iter_bookmarks(self) -> Iterator[Bookmark]:
        """Yield every bookmark across all roots."""
        for _, folder in self.roots:
            yield from folder.iter_bookmarks()

    def urls(self) -> list[str]:
        """Every URL across all roots, in tree order (duplicates kept)."""
        return [bm.url for bm in self.iter_bookmarks()]


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """A rule's match criteria; a criterion left None is ignored."""

    domain: str | None = None
    url_prefix: str | None = None
    title_regex: str | None = None


@dataclass(frozen=True, slots=True)
class Rule:
    """A deterministic classification rule. ``ref`` is optional."""

    match: RuleMatch
    folder: FolderPath
    ref: FolderPath | None = None
    source: RuleSource = "human"


@dataclass(frozen=True, slots=True)
class Assignment:
    """Where one bookmark lands: an intent ``folder`` and a ``ref`` category."""

    bookmark: Bookmark
    folder: FolderPath
    ref: FolderPath
    confidence: float
    via: AssignmentVia


@dataclass(frozen=True, slots=True)
class CreateFolder:
    """Plan op: create a folder at ``path``."""

    path: FolderPath


@dataclass(frozen=True, slots=True)
class RenameFolder:
    """Plan op: rename ``old`` to ``new``."""

    old: FolderPath
    new: FolderPath


@dataclass(frozen=True, slots=True)
class DeleteFolder:
    """Plan op: delete the folder at ``path``."""

    path: FolderPath


FolderOp = CreateFolder | RenameFolder | DeleteFolder


@dataclass(frozen=True, slots=True)
class DedupeGroup:
    """A survivor and the duplicate copies collapsed into it."""

    kept: Bookmark
    dropped: tuple[Bookmark, ...]


@dataclass(frozen=True, slots=True)
class Plan:
    """The dry-run report and the apply worklist, as one value."""

    moves: tuple[Assignment, ...] = ()
    dedupes: tuple[DedupeGroup, ...] = ()
    folder_ops: tuple[FolderOp, ...] = ()
    learned_rules: tuple[Rule, ...] = field(default=())
