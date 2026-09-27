"""Use case: an entry is placed (DYNOMARK.DESIGN.md, Behaviors and Interfaces;
Placement policy).

Neighbours by embedding among placed entries, the completion's folder
choice admitted by the domain policy, the placement and its reason recorded
before ``file`` builds a batch.
"""

from collections.abc import Sequence
from typing import Final

from dynomark_daemon.domain.bookmark import CorpusEntry, Enrichment, embedding_text
from dynomark_daemon.domain.placement import (
    EntryRef,
    MoveFeedback,
    Placement,
    PlacementReason,
    admit_folder,
)
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import TreeOutline
from dynomark_daemon.ports.clock import Clock
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.store import CorpusStorePort

NEIGHBOURS: Final = 5
"""How many placed neighbours the completion is shown."""


def _vector(entry: CorpusEntry, *, embedding: EmbeddingPort) -> tuple[float, ...]:
    """The entry's vector in the model the store's neighbours were embedded by."""
    if entry.embedding.model_id == embedding.model().model_id:
        return entry.embedding.vector
    about = Enrichment(summary=entry.summary, tags=entry.tags)
    return embedding.embed(embedding_text(entry.bookmark, about)).vector


def _neighbours(
    entry: CorpusEntry, *, store: CorpusStorePort, embedding: EmbeddingPort
) -> tuple[EntryRef, ...]:
    candidates = store.knn_candidates(
        _vector(entry, embedding=embedding), limit=NEIGHBOURS + 1, placed_only=True
    )
    refs: list[EntryRef] = []
    for candidate in candidates:
        neighbour = store.get_entry(candidate.identity)
        placement = store.get_placement(candidate.identity)
        if candidate.identity == entry.identity or not neighbour or not placement:
            continue
        refs.append(
            EntryRef(
                identity=neighbour.identity,
                title=neighbour.bookmark.title,
                path=placement.folder,
            )
        )
    return tuple(refs[:NEIGHBOURS])


def place(
    entry: CorpusEntry,
    outline: TreeOutline,
    feedback: Sequence[MoveFeedback],
    role: HostRole,
    *,
    store: CorpusStorePort,
    embedding: EmbeddingPort,
    completion: CompletionPort,
    clock: Clock,
) -> Placement | NotWriter:
    """Choose and record the folder ``entry`` is filed into.

    Raises:
        CompletionError: the completion could not choose.
        NoAdmissibleFolder: every folder of the outline is locked.
    """
    if role is HostRole.READER:
        return NotWriter(use_case="place")
    neighbours = _neighbours(entry, store=store, embedding=embedding)
    choice = completion.choose_folder(
        entry, neighbours=neighbours, outline=outline, feedback=feedback
    )
    folder = admit_folder(choice.folder, outline, [n.path for n in neighbours])
    placement = Placement(
        identity=entry.identity,
        reason=PlacementReason(
            folder=folder,
            neighbours=neighbours,
            rationale=choice.rationale,
            feedback_ids=tuple(f.feedback_id for f in feedback),
            model_id=completion.model().model_id,
        ),
        created_at=clock.now_ms(),
    )
    store.put_placement(placement)
    return placement
