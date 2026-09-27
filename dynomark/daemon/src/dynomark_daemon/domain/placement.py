"""Where an entry is filed and why; observed moves and the feedback they give."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.ids import FeedbackId, NodeId
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import (
    WRITER_MARKER_PREFIX,
    FolderPath,
    OwnedRoots,
    TreeOutline,
)


@dataclass(frozen=True, slots=True)
class EntryRef:
    """A reference to a corpus entry: identity, title, and where it is filed."""

    identity: Identity
    title: str
    path: FolderPath


@dataclass(frozen=True, slots=True)
class PlacementReason:
    """Why an entry is in ``folder``: neighbours, rationale, feedback, model."""

    folder: FolderPath
    neighbours: tuple[EntryRef, ...]
    rationale: str
    feedback_ids: tuple[FeedbackId, ...]
    model_id: str


@dataclass(frozen=True, slots=True)
class Placement:
    """The folder chosen for an entry plus its ``PlacementReason``."""

    identity: Identity
    reason: PlacementReason
    created_at: int

    @property
    def folder(self) -> FolderPath:
        return self.reason.folder


@dataclass(frozen=True, slots=True)
class FolderChoice:
    """What the completion model answers when asked where an entry belongs."""

    folder: FolderPath
    rationale: str


class MoveOrigin(StrEnum):
    USER = "user"
    EXTENSION = "extension"


@dataclass(frozen=True, slots=True)
class Move:
    """An observed tree move; ``url`` is absent for a folder."""

    node_id: NodeId
    from_path: FolderPath
    to_path: FolderPath
    origin: MoveOrigin
    observed_at: int
    url: str | None = None


@dataclass(frozen=True, slots=True)
class MoveFeedback:
    """A user ``Move`` between owned folders, kept as a labelled example."""

    feedback_id: FeedbackId
    identity: Identity
    from_path: FolderPath
    to_path: FolderPath
    observed_at: int


# --- Placement policy (DYNOMARK.DESIGN.md, "Placement policy") ---


class NoAdmissibleFolder(Exception):
    """Nothing in the ``Dynomark`` subtree may receive a placement."""


def is_admissible(path: FolderPath, outline: TreeOutline) -> bool:
    """Inside the ``Dynomark`` subtree, not in or under a locked folder, and
    no writer marker (markers are excluded from placement)."""
    return (
        path.is_inside(outline.root)
        and not outline.is_locked(path)
        and not any(name.startswith(WRITER_MARKER_PREFIX) for name in path.names)
    )


def _same_name(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _child_named(
    outline: TreeOutline, parent: FolderPath, name: str
) -> FolderPath | None:
    """The existing child folder ``name`` names: exactly, else by collision."""
    children = outline.children_of(parent)
    exact = next((c.path for c in children if c.path.names[-1] == name), None)
    if exact is not None:
        return exact
    return next((c.path for c in children if _same_name(c.path.names[-1], name)), None)


def resolve_choice(choice: FolderPath, outline: TreeOutline) -> FolderPath | None:
    """The folder a completion's choice names: an existing folder, or one new
    leaf under the deepest existing one (a colliding leaf is the existing
    folder; levels past the first new one are dropped). ``None`` when the
    choice is outside the ``Dynomark`` subtree."""
    if not choice.is_inside(outline.root):
        return None
    current = outline.root
    for name in choice.names[len(outline.root.names) :]:
        existing = _child_named(outline, current, name)
        if existing is None:
            return current.child(name.strip())
        current = existing
    return current


def admit_folder(
    choice: FolderPath,
    outline: TreeOutline,
    neighbour_folders: Sequence[FolderPath],
) -> FolderPath:
    """Where an entry goes: the completion's choice when admissible; else the
    admissible folder most of its neighbours sit in (a sibling of a locked
    choice); else the ``Dynomark`` root.

    Raises:
        NoAdmissibleFolder: the root itself is locked.
    """
    resolved = resolve_choice(choice, outline)
    if resolved is not None and is_admissible(resolved, outline):
        return resolved
    usable = [
        folder
        for folder in neighbour_folders
        if is_admissible(folder, outline) and outline.folder_at(folder) is not None
    ]
    if usable:
        return Counter(usable).most_common(1)[0][0]
    if is_admissible(outline.root, outline):
        return outline.root
    raise NoAdmissibleFolder(f"every folder under {outline.root.names} is locked")


# --- Feedback (Ubiquitous language: Move, MoveFeedback) ---


def feedback_of(move: Move, role: HostRole, roots: OwnedRoots) -> MoveFeedback | None:
    """The labelled example a move gives, if any: only a user's move of a
    bookmark between two owned folders, observed on the writer. Its id is
    derived from (node, time), so a repeat is the same feedback."""
    if (
        role is not HostRole.WRITER
        or move.origin is not MoveOrigin.USER
        or move.url is None
        or not roots.contains(move.from_path)
        or not roots.contains(move.to_path)
    ):
        return None
    return MoveFeedback(
        feedback_id=FeedbackId(f"fb-{move.node_id}-{move.observed_at}"),
        identity=Identity.from_url(move.url),
        from_path=move.from_path,
        to_path=move.to_path,
        observed_at=move.observed_at,
    )
