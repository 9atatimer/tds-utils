"""Use case: the local index is built (DYNOMARK.DESIGN.md, Behaviors and
Interfaces; contract/v1 README, ``index.pull`` keyset by identity).
"""

from dataclasses import dataclass
from typing import Final

from dynomark_daemon.app.search import filed_path
from dynomark_daemon.domain.bookmark import CorpusEntry, Identity
from dynomark_daemon.domain.search import LocalIndex, LocalIndexRow, index_row
from dynomark_daemon.ports.store import CorpusStorePort

BUILD_PAGE: Final = 1000


@dataclass(frozen=True, slots=True)
class LocalIndexPage:
    """Rows after a keyset position; ``next_after`` is ``None`` on the last."""

    rows: tuple[LocalIndexRow, ...]
    next_after: Identity | None


def _row(entry: CorpusEntry, *, store: CorpusStorePort) -> LocalIndexRow | None:
    return index_row(
        entry.identity,
        title=entry.bookmark.title,
        path=filed_path(entry, store=store),
        tags=entry.tags,
        summary=entry.summary,
    )


def local_index_page(
    after: Identity | None, limit: int, *, store: CorpusStorePort
) -> LocalIndexPage:
    """Up to ``limit`` entries after ``after`` by identity, as rows; an entry
    whose row cannot fit is left out and the page still moves past it."""
    entries = store.list_entries(after=after, limit=limit + 1)
    page = entries[:limit]
    rows = (_row(entry, store=store) for entry in page)
    return LocalIndexPage(
        rows=tuple(row for row in rows if row is not None),
        next_after=page[-1].identity if len(entries) > limit else None,
    )


def build_local_index(*, store: CorpusStorePort) -> LocalIndex:
    """One row per corpus entry, each within 512 bytes."""
    rows: list[LocalIndexRow] = []
    after: Identity | None = None
    while True:
        page = local_index_page(after, BUILD_PAGE, store=store)
        rows.extend(page.rows)
        if page.next_after is None:
            return LocalIndex(rows=tuple(rows))
        after = page.next_after
