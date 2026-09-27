"""Use case: the local index is built (DYNOMARK.DESIGN.md, Behaviors and
Interfaces; contract/v1 README, ``index.pull``: cursors stay valid across
data changes).

Pages are keyset by the store position of an entry, which is kept when the
entry is replaced and grows with every new identity; the cursor carries
that number, so it is compact however long the identities are.
"""

from typing import Final

from dynomark_daemon.app.pages import Page, StaleCursor, mint_cursor, read_cursor
from dynomark_daemon.app.search import filed_path
from dynomark_daemon.domain.bookmark import CorpusEntry
from dynomark_daemon.domain.search import LocalIndex, LocalIndexRow, index_row
from dynomark_daemon.ports.store import CorpusStorePort

BUILD_PAGE: Final = 1000
CURSOR_KIND: Final = "index"


def _row(entry: CorpusEntry, *, store: CorpusStorePort) -> LocalIndexRow | None:
    return index_row(
        entry.identity,
        title=entry.bookmark.title,
        path=filed_path(entry, store=store),
        tags=entry.tags,
        summary=entry.summary,
    )


def _position(cursor: str | None) -> int | None:
    """The store position a cursor resumes after.

    Raises:
        StaleCursor: the cursor is not one of the index's.
    """
    if cursor is None:
        return None
    key = read_cursor(cursor, CURSOR_KIND, "")
    if not key.isdecimal():
        raise StaleCursor("index cursor does not name a position")
    return int(key)


def local_index_page(
    cursor: str | None, limit: int, *, store: CorpusStorePort
) -> Page[LocalIndexRow]:
    """Up to ``limit`` entries after the cursor, as rows; an entry whose row
    cannot fit is left out and the page still moves past it.

    Raises:
        StaleCursor: the cursor is not one of the index's (``stale_cursor``).
    """
    stored = store.list_entries(after=_position(cursor), limit=limit + 1)
    page = stored[:limit]
    rows = (_row(s.entry, store=store) for s in page)
    more = len(stored) > limit
    return Page(
        items=tuple(row for row in rows if row is not None),
        next_cursor=(
            mint_cursor(CURSOR_KIND, "", str(page[-1].position)) if more else None
        ),
    )


def build_local_index(*, store: CorpusStorePort) -> LocalIndex:
    """One row per corpus entry, each within 512 bytes."""
    rows: list[LocalIndexRow] = []
    cursor: str | None = None
    while True:
        page = local_index_page(cursor, BUILD_PAGE, store=store)
        rows.extend(page.items)
        if page.next_cursor is None:
            return LocalIndex(rows=tuple(rows))
        cursor = page.next_cursor
