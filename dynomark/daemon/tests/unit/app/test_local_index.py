"""Behaviors row: The local index is built (DYNOMARK.DESIGN.md, Behaviors and
Interfaces) -- ``build_local_index(*, store) -> LocalIndex``: "Given the
corpus, When built, Then rows hold exactly identity, title, path, tags,
one-line summary"; Ubiquitous language: "at most 512 bytes per entry".
Contract v1 (Size limits): the 512 bytes are the row's compact UTF-8 JSON;
the daemon trims summary, then tags, then title, and leaves out a row whose
identity alone cannot fit. ``index.pull`` pages keyset by identity.
"""

import dataclasses

from hypothesis import given, settings
from hypothesis import strategies as st

from dynomark_daemon.app.index import build_local_index, local_index_page
from dynomark_daemon.domain.bookmark import CorpusEntry, Identity
from dynomark_daemon.domain.search import LocalIndexRow
from dynomark_daemon.testing.store import InMemoryCorpusStore
from dynomark_daemon.wire.mapping import local_index_row_to_wire
from tests._factories import make_entry, make_path, make_placement

MAX_ROW_BYTES = 512
RUST = make_path("Dynomark", "Rust")


def _wire_bytes(row: LocalIndexRow) -> int:
    return len(local_index_row_to_wire(row).model_dump_json().encode("utf-8"))


def _store(*entries: CorpusEntry) -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    for entry in entries:
        store.put_entry(entry)
    return store


def test_build_local_index_rows_hold_exactly_the_five_fields() -> None:
    """Given a placed entry, When the index is built, Then its row holds exactly
    identity, title, path (its placement folder), tags and the summary's first
    line, and nothing else goes on the wire."""
    entry = make_entry(
        title="Tokio tutorial",
        summary="An async runtime.\nIt schedules tasks.",
        tags=("rust", "async"),
        text="captured words never leave the daemon",
    )
    store = _store(entry)
    store.put_placement(make_placement(entry.identity.value, folder=RUST))

    (row,) = build_local_index(store=store).rows

    assert [f.name for f in dataclasses.fields(LocalIndexRow)] == [
        "identity",
        "title",
        "path",
        "tags",
        "summary",
    ]
    assert row == LocalIndexRow(
        identity=entry.identity,
        title="Tokio tutorial",
        path=RUST,
        tags=("rust", "async"),
        summary="An async runtime.",
    )
    wire = local_index_row_to_wire(row).model_dump(by_alias=True)
    assert set(wire) == {"identity", "title", "path", "tags", "summary"}


def test_build_local_index_has_one_row_per_entry_by_identity() -> None:
    """Given three entries, When built, Then there is one row each, by identity;
    an unplaced entry's path is where it was saved."""
    urls = ["https://c.example/", "https://a.example/", "https://b.example/"]
    store = _store(*(make_entry(url) for url in urls))

    rows = build_local_index(store=store).rows

    assert [r.identity.value for r in rows] == sorted(urls)
    assert {r.path for r in rows} == {make_path("Follow Up")}


def test_build_local_index_trims_summary_then_tags_then_title_to_512_bytes() -> None:
    """Given entries whose rows would exceed 512 bytes, When built, Then each row
    fits: the summary is trimmed first, then tags, then the title."""
    long_summary = make_entry("https://s.example/", summary="é" * 600, tags=("t",))
    long_tags = make_entry(
        "https://t.example/",
        title="kept",
        tags=tuple(f"tag-{i:02d}-" + "x" * 50 for i in range(12)),
    )
    long_title = make_entry("https://u.example/", title="題" * 400)

    rows = {
        r.identity.value: r
        for r in build_local_index(
            store=_store(long_summary, long_tags, long_title)
        ).rows
    }

    assert all(_wire_bytes(r) <= MAX_ROW_BYTES for r in rows.values())
    summary_row = rows["https://s.example/"]
    assert summary_row.tags == ("t",) and 0 < len(summary_row.summary) < 600
    tags_row = rows["https://t.example/"]
    assert tags_row.title == "kept" and 0 < len(tags_row.tags) < 12
    title_row = rows["https://u.example/"]
    assert 0 < len(title_row.title) < 400


def test_build_local_index_leaves_out_a_row_whose_identity_cannot_fit() -> None:
    """Given an entry whose identity alone exceeds 512 bytes, When built, Then
    it has no row (tier 2 still finds it)."""
    huge = make_entry("https://example.org/" + "a" * 600)
    store = _store(huge, make_entry("https://small.example/"))

    rows = build_local_index(store=store).rows

    assert [r.identity.value for r in rows] == ["https://small.example/"]


@settings(max_examples=50)
@given(
    title=st.text(max_size=300),
    summary=st.text(max_size=700),
    tags=st.lists(st.text(min_size=1, max_size=80), max_size=40),
)
def test_every_built_row_fits_512_bytes_and_the_wire(
    title: str, summary: str, tags: list[str]
) -> None:
    """Given any title, summary and tags, When the index is built, Then the row
    exists (a short identity always fits), is a valid wire LocalIndexRow, and
    is at most 512 bytes."""
    entry = make_entry(
        "https://p.example/", title=title, summary=summary, tags=tuple(tags)
    )

    (row,) = build_local_index(store=_store(entry)).rows

    assert _wire_bytes(row) <= MAX_ROW_BYTES


def test_local_index_pages_by_identity_and_survive_inserts() -> None:
    """Given four entries, When paged two at a time and an entry is added before
    the cursor between pages, Then the pages hold every original entry once in
    identity order and the last page says so (keyset: cursors stay valid
    across data changes)."""
    store = _store(*(make_entry(f"https://{c}.example/") for c in "bdfh"))

    first = local_index_page(None, 2, store=store)
    store.put_entry(make_entry("https://a.example/"))
    second = local_index_page(first.next_after, 2, store=store)

    assert [r.identity.value for r in first.rows] == [
        "https://b.example/",
        "https://d.example/",
    ]
    assert [r.identity.value for r in second.rows] == [
        "https://f.example/",
        "https://h.example/",
    ]
    assert first.next_after == Identity("https://d.example/")
    assert second.next_after is None
