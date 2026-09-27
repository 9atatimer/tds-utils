"""CorpusStorePort contract: one suite, every implementation.

STORES names each implementation by a factory taking a per-test temporary
directory; the in-memory fake is here now, and the SQLite adapter
(task-025) registers beside it and must pass the same tests unchanged.

Design: Data Model ("one corpus_entry per identity"), Seams ("Corpus
store ... SQLite with FTS5 and a vector extension / in-memory fake"), Key
Decisions ("Hybrid ranking: fusion in the domain over the store's two
candidate lists"); contract/v1/README.md, Delivery and replay
("index.pull cursors ... keyset by identity") and the idempotency table.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.ports.store import CorpusStorePort
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_entry, make_path, make_placement

pytestmark = pytest.mark.contract

STORES: dict[str, Callable[[Path], CorpusStorePort]] = {
    "memory": lambda _tmp: InMemoryCorpusStore(),
}


@pytest.fixture(params=sorted(STORES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> CorpusStorePort:
    return STORES[request.param](tmp_path)


# --- Entries ---


def test_get_entry_returns_the_entry_put(store: CorpusStorePort) -> None:
    """Given a stored entry, When read by identity, Then it is the same value."""
    entry = make_entry(summary="a runtime", tags=("rust",), text="Tokio text")
    store.put_entry(entry)

    assert store.get_entry(entry.identity) == entry


def test_get_entry_of_unknown_identity_is_none(store: CorpusStorePort) -> None:
    """Given an empty store, When an identity is read, Then there is no entry."""
    assert store.get_entry(Identity("https://unknown.example/")) is None


def test_put_entry_twice_keeps_one_entry_per_identity(store: CorpusStorePort) -> None:
    """Given an entry, When another with the same identity is put, Then it
    replaces the first (one corpus_entry per identity)."""
    store.put_entry(make_entry(summary="old"))
    store.put_entry(newer := make_entry(summary="new"))

    assert store.list_entries(limit=10) == [newer]


def test_list_entries_pages_by_identity_keyset(store: CorpusStorePort) -> None:
    """Given entries put out of order, When listed in pages of two after the last
    identity seen, Then every entry comes once, ordered by identity."""
    urls = ["https://c.example/", "https://a.example/", "https://b.example/"]
    for url in urls:
        store.put_entry(make_entry(url))

    first = store.list_entries(limit=2)
    rest = store.list_entries(after=first[-1].identity, limit=2)

    assert [e.identity.value for e in first + rest] == sorted(urls)


# --- Placements ---


def test_get_placement_returns_the_latest_put(store: CorpusStorePort) -> None:
    """Given a placement replaced by another for the same identity, When read,
    Then the latest is returned; an unplaced identity has none."""
    store.put_placement(make_placement(folder=make_path("Dynomark", "Rust")))
    store.put_placement(latest := make_placement(folder=make_path("Dynomark", "Go")))

    assert store.get_placement(latest.identity) == latest
    assert store.get_placement(Identity("https://unplaced.example/")) is None
