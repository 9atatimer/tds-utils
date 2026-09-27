"""Tier-2 search, one page at a time (contract/v1 README: ``search`` is
paginated; "``search`` repeats its ``query`` on every page"; a cursor is
valid only for the parameters that minted it; Size limits: ``Cursor`` is
at most 1,024 printable ASCII characters).

The page is a window on ``search_corpus``'s ranking, so the cursor carries
an offset, never an identity (identities run to 65,536 code points).
"""

import pytest

from dynomark_daemon.app.pages import StaleCursor
from dynomark_daemon.app.search import search_page
from dynomark_daemon.domain.search import HitTier, Query
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_entry


def _store(*urls: str) -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    for url in urls:
        store.put_entry(make_entry(url, text="tokio runtime scheduling"))
    return store


def test_search_page_walks_the_ranking_in_pages() -> None:
    """Given five entries matching a query, When searched two at a time, Then
    the pages hold every hit once, in rank order, all of tier corpus, and the
    last page has no cursor."""
    store = _store(*(f"https://{c}.example/" for c in "abcde"))
    embedding = HashingEmbedding()
    query = Query("tokio")

    pages = [search_page(query, None, 2, store=store, embedding=embedding)]
    while (cursor := pages[-1].next_cursor) is not None:
        pages.append(search_page(query, cursor, 2, store=store, embedding=embedding))

    hits = [hit for page in pages for hit in page.items]
    assert [len(page.items) for page in pages] == [2, 2, 1]
    assert len({hit.identity for hit in hits}) == 5
    assert [hit.score for hit in hits] == sorted((h.score for h in hits), reverse=True)
    assert {hit.tier for hit in hits} == {HitTier.CORPUS}


def test_search_cursor_is_compact_whatever_the_identity() -> None:
    """Given hits whose identities are longer than a Cursor may be, When the
    first page is read, Then its cursor is at most 1,024 printable ASCII."""
    store = _store(*("https://example.org/" + c * 60_000 for c in "ab"))

    page = search_page(
        Query("tokio"), None, 1, store=store, embedding=HashingEmbedding()
    )

    assert page.next_cursor is not None and len(page.next_cursor) <= 1024
    assert all("!" <= ch <= "~" for ch in page.next_cursor)


def test_search_cursor_of_another_query_is_stale() -> None:
    """Given a cursor minted for one query, When presented with another query,
    Then StaleCursor is raised."""
    store = _store("https://a.example/", "https://b.example/")
    embedding = HashingEmbedding()
    cursor = search_page(
        Query("tokio"), None, 1, store=store, embedding=embedding
    ).next_cursor
    assert cursor is not None

    with pytest.raises(StaleCursor):
        search_page(Query("runtime"), cursor, 1, store=store, embedding=embedding)
