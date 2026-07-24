"""Unit tests for the Netscape HTML source/sink and round-trip losslessness."""

from __future__ import annotations

import re
from pathlib import Path

from orgmarks.adapters.netscape import (
    NetscapeSink,
    NetscapeSource,
    emit_netscape,
    parse_netscape,
)
from orgmarks.domain.model import BookmarkTree, FolderPath

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _hrefs_in(text: str) -> set[str]:
    return set(re.findall(r'HREF="([^"]+)"', text, flags=re.IGNORECASE))


def test_parse_maps_top_level_folders_to_roots() -> None:
    """Given a simple export, When parsed, Then roots map by folder name."""
    tree = parse_netscape((FIXTURES / "simple.html").read_text())
    root_names = [name for name, _ in tree.roots]
    assert root_names == ["bookmarks_bar", "other"]


def test_parse_reads_titles_dates_and_unescapes() -> None:
    """Given a link with an entity, When parsed, Then title is unescaped."""
    tree = parse_netscape((FIXTURES / "simple.html").read_text())
    bar = tree.root("bookmarks_bar")
    alpha = bar.bookmarks[0]
    assert alpha.url == "https://example.com/alpha"
    assert alpha.title == "Alpha & Co"
    assert alpha.add_date == 1600000001


def test_parse_stamps_source_path() -> None:
    """Given a nested export, When parsed, Then source_path reflects location."""
    tree = parse_netscape((FIXTURES / "nested.html").read_text())
    bar = tree.root("bookmarks_bar")
    dev = next(f for f in bar.subfolders if f.name == "Dev")
    tools = next(f for f in dev.subfolders if f.name == "Tools")
    tool_x = tools.bookmarks[0]
    assert tool_x.source_path == FolderPath.from_string("bookmarks_bar/Dev/Tools")


def test_losslessness_every_url_survives_parse() -> None:
    """Given an export, When parsed, Then the URL set equals the file's."""
    text = (FIXTURES / "nested.html").read_text()
    tree = parse_netscape(text)
    assert set(tree.urls()) == _hrefs_in(text)


def test_round_trip_parse_emit_parse_is_identical() -> None:
    """Given a tree, When emitted and re-parsed, Then the tree is identical."""
    original = parse_netscape((FIXTURES / "nested.html").read_text())
    reparsed = parse_netscape(emit_netscape(original))
    assert reparsed == original


def test_emit_places_links_before_subfolders() -> None:
    """Given a hub with a link and a folder, When emitted, Then link is first."""
    tree = parse_netscape((FIXTURES / "nested.html").read_text())
    out = emit_netscape(tree)
    top_pos = out.index('HREF="https://example.com/top"')
    dev_pos = out.index('<H3 ADD_DATE="1600000002">Dev</H3>')
    assert top_pos < dev_pos


def test_source_and_sink_use_files(tmp_path: Path) -> None:
    """Given a file, When NetscapeSource loads it, Then a tree returns."""
    src_file = FIXTURES / "simple.html"
    tree: BookmarkTree = NetscapeSource().load(src_file)
    out = NetscapeSink().emit(tree)
    assert _hrefs_in(out) == set(tree.urls())
    dest = tmp_path / "out.html"
    dest.write_text(out)
    assert NetscapeSource().load(dest) == tree
