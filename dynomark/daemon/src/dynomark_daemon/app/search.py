"""Use case: tier-2 search over the corpus (DYNOMARK.DESIGN.md, Behaviors and
Interfaces, "Tier-2 search").
"""

from typing import Final

from dynomark_daemon.app.pages import Page, offset_page
from dynomark_daemon.domain.bookmark import CorpusEntry
from dynomark_daemon.domain.search import Candidate, Hit, HitTier, Query, fuse
from dynomark_daemon.domain.tree import FolderPath
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.store import CorpusStorePort

CANDIDATES: Final = 50
"""How many rows each store candidate list contributes."""


def filed_path(entry: CorpusEntry, *, store: CorpusStorePort) -> FolderPath:
    """Where the entry is: its placement's folder, else where it was saved."""
    placement = store.get_placement(entry.identity)
    return entry.bookmark.path if placement is None else placement.folder


def _hit(candidate: Candidate, *, store: CorpusStorePort) -> Hit | None:
    entry = store.get_entry(candidate.identity)
    if entry is None:
        return None
    return Hit(
        identity=entry.identity,
        title=entry.bookmark.title,
        path=filed_path(entry, store=store),
        score=candidate.score,
        tier=HitTier.CORPUS,
    )


def search_corpus(
    query: Query, *, store: CorpusStorePort, embedding: EmbeddingPort
) -> list[Hit]:
    """Corpus hits for ``query``, best first, every one of tier ``corpus``:
    the store's full-text and nearest-neighbour candidates, fused."""
    candidates = fuse(
        store.text_candidates(query, limit=CANDIDATES),
        store.knn_candidates(embedding.embed(query.text).vector, limit=CANDIDATES),
    )
    hits = (_hit(candidate, store=store) for candidate in candidates)
    return [hit for hit in hits if hit is not None]


def search_page(
    query: Query,
    cursor: str | None,
    limit: int,
    *,
    store: CorpusStorePort,
    embedding: EmbeddingPort,
) -> Page[Hit]:
    """One page of ``search_corpus``'s hits for ``query`` (``search.result``).

    Raises:
        StaleCursor: the cursor belongs to another query or list.
    """
    hits = search_corpus(query, store=store, embedding=embedding)
    return offset_page(
        hits, kind="search", params=query.text, cursor=cursor, limit=limit
    )
