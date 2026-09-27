"""Where an entry is filed and why; observed moves and the feedback they give."""

from dataclasses import dataclass
from enum import StrEnum

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.ids import FeedbackId, NodeId
from dynomark_daemon.domain.tree import FolderPath


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
