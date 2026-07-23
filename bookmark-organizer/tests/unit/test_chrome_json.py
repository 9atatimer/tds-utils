"""Unit tests for the read-only Chrome Bookmarks JSON loader."""

from __future__ import annotations

from pathlib import Path

from orgmarks.adapters.chrome_json import ChromeJsonSource, parse_chrome_json
from orgmarks.domain.model import BookmarkTree, FolderPath

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _tree() -> BookmarkTree:
    return parse_chrome_json((FIXTURES / "Bookmarks.json").read_text())


def test_roots_map_to_chrome_root_names() -> None:
    """Given a profile file, When parsed, Then roots map by key order."""
    tree = _tree()
    assert [name for name, _ in tree.roots] == ["bookmarks_bar", "other", "synced"]


def test_date_added_converts_from_windows_microseconds() -> None:
    """Given a Chrome timestamp, When parsed, Then it becomes unix seconds."""
    tree = _tree()
    top = tree.root("bookmarks_bar").bookmarks[0]
    assert top.url == "https://example.com/top"
    assert top.add_date == 1600000001


def test_guid_is_preserved() -> None:
    """Given a url node with a guid, When parsed, Then the guid carries over."""
    tree = _tree()
    top = tree.root("bookmarks_bar").bookmarks[0]
    assert top.guid == "00000000-0000-4000-8000-000000000002"


def test_nested_folder_structure_and_source_path() -> None:
    """Given nested folders, When parsed, Then structure and paths hold."""
    tree = _tree()
    bar = tree.root("bookmarks_bar")
    dev = next(f for f in bar.subfolders if f.name == "Dev")
    tools = next(f for f in dev.subfolders if f.name == "Tools")
    tool_x = tools.bookmarks[0]
    assert tool_x.url == "https://example.com/dev/tools/x"
    assert tool_x.source_path == FolderPath.from_string("bookmarks_bar/Dev/Tools")


def test_all_urls_present() -> None:
    """Given a profile, When parsed, Then every url node appears."""
    tree = _tree()
    assert set(tree.urls()) == {
        "https://example.com/top",
        "https://example.com/dev/1",
        "https://example.com/dev/tools/x",
        "https://example.com/loose",
    }


def test_source_loads_from_path() -> None:
    """Given the source adapter, When load() is called, Then a tree returns."""
    tree = ChromeJsonSource().load(FIXTURES / "Bookmarks.json")
    assert "https://example.com/loose" in tree.urls()


def test_missing_date_added_is_zero() -> None:
    """Given a node without date_added, When parsed, Then add_date is 0."""
    text = '{"roots": {"other": {"type": "folder", "name": "Other bookmarks",'
    text += (
        ' "children": [{"type": "url", "name": "N", "url": "https://example.com/n"}]}}}'
    )
    tree = parse_chrome_json(text)
    assert tree.root("other").bookmarks[0].add_date == 0
