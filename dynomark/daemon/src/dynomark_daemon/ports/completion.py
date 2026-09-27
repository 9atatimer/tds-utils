"""Seam: the completion vendor and model (model id at the edge).

One method per question the daemon asks a model; each returns a domain
value, so a use case never parses vendor text.
"""

from collections.abc import Sequence
from typing import Protocol

from dynomark_daemon.domain.bookmark import Bookmark, Capture, CorpusEntry, Enrichment
from dynomark_daemon.domain.chat import DraftAnswer, Question, Turn
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.diff import DiffKind, DiffProposal
from dynomark_daemon.domain.placement import EntryRef, FolderChoice, MoveFeedback
from dynomark_daemon.domain.tree import TreeOutline
from dynomark_daemon.ports.errors import PortError


class CompletionError(PortError):
    """The completion call failed or returned something unusable."""


class CompletionPort(Protocol):
    def model(self) -> ModelInfo:
        """The model this port completes with."""
        ...

    def enrich(self, bookmark: Bookmark, capture: Capture) -> Enrichment:
        """Summary and tags for a captured bookmark."""
        ...

    def choose_folder(
        self,
        entry: CorpusEntry,
        *,
        neighbours: Sequence[EntryRef],
        outline: TreeOutline,
        feedback: Sequence[MoveFeedback],
    ) -> FolderChoice:
        """An existing owned folder, or one new leaf under one, for ``entry``."""
        ...

    def answer(
        self,
        question: Question,
        *,
        history: Sequence[Turn],
        context: Sequence[CorpusEntry],
    ) -> DraftAnswer:
        """A reply grounded in ``context``, naming the identities it cites."""
        ...

    def propose_diff(
        self, kind: DiffKind, *, outline: TreeOutline, own_bar: TreeOutline
    ) -> tuple[DiffProposal, ...]:
        """Items of an ``audit`` or ``rebuild`` diff between two outlines."""
        ...
