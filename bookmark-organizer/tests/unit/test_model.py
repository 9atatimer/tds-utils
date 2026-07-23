"""Unit tests for the immutable bookmark model."""

from __future__ import annotations

import dataclasses

import pytest

from orgmarks.domain.model import (
    Assignment,
    Bookmark,
    BookmarkTree,
    DedupeGroup,
    Folder,
    FolderPath,
    Plan,
    Rule,
    RuleMatch,
)
from orgmarks.domain.taxonomy import Intent, Taxonomy


def _bm(url: str, path: FolderPath, add_date: int = 100) -> Bookmark:
    return Bookmark(url=url, title=url, add_date=add_date, source_path=path)


def test_from_string_splits_and_drops_empty_segments() -> None:
    """Given a slash string, When parsed, Then empty segments are dropped."""
    path = FolderPath.from_string("/work//dev/")
    assert path.parts == ("work", "dev")
    assert str(path) == "work/dev"


def test_folderpath_name_depth_parent_child() -> None:
    """Given a path, When queried, Then name/depth/parent/child are correct."""
    path = FolderPath.from_string("work/dev/tools")
    assert path.name == "tools"
    assert path.depth == 3
    assert path.parent == FolderPath.from_string("work/dev")
    assert path.child("x") == FolderPath.from_string("work/dev/tools/x")


def test_folderpath_root_has_no_parent() -> None:
    """Given a depth-1 path, When parent, Then None."""
    assert FolderPath.from_string("work").parent is None
    assert FolderPath(()).parent is None


def test_folderpath_is_under_prefix() -> None:
    """Given a path, When checked against a prefix, Then is_under is True."""
    child = FolderPath.from_string("work/dev/tools")
    assert child.is_under(FolderPath.from_string("work/dev"))
    assert not child.is_under(FolderPath.from_string("fun"))


def test_bookmark_is_frozen() -> None:
    """Given a Bookmark, When an attribute is set, Then it raises."""
    bm = _bm("https://example.com/a", FolderPath.from_string("work"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        bm.url = "https://example.com/b"  # type: ignore[misc]


def test_folder_hub_leaf_and_iter_bookmarks() -> None:
    """Given a nested folder, When iterated, Then all bookmarks yield."""
    root_path = FolderPath.from_string("work")
    leaf = Folder(
        name="dev",
        bookmarks=(_bm("https://example.com/1", root_path.child("dev")),),
    )
    hub = Folder(
        name="work",
        subfolders=(leaf,),
        bookmarks=(_bm("https://example.com/0", root_path),),
    )
    assert hub.is_hub and not hub.is_leaf
    assert leaf.is_leaf and not leaf.is_hub
    urls = [bm.url for bm in hub.iter_bookmarks()]
    assert urls == ["https://example.com/0", "https://example.com/1"]


def test_tree_urls_and_root_lookup() -> None:
    """Given a tree, When urls() is called, Then every url appears in order."""
    bar = Folder(
        name="bookmarks_bar",
        bookmarks=(_bm("https://example.com/a", FolderPath.from_string("bar")),),
    )
    other = Folder(
        name="other",
        bookmarks=(_bm("https://example.com/b", FolderPath.from_string("other")),),
    )
    tree = BookmarkTree(roots=(("bookmarks_bar", bar), ("other", other)))
    assert tree.urls() == ["https://example.com/a", "https://example.com/b"]
    assert tree.root("bookmarks_bar") is bar
    assert tree.root("synced").name == "synced"


def test_taxonomy_is_intent_path_and_names() -> None:
    """Given a taxonomy, When a path is checked, Then intent roots match."""
    tax = Taxonomy(
        version=1,
        intents=(Intent(name="work"), Intent(name="fun", hint="leisure")),
        pins=(),
        rules=(),
        reference_root=FolderPath.from_string("other/Reference"),
    )
    assert tax.intent_names() == ("work", "fun")
    assert tax.is_intent_path(FolderPath.from_string("work/dev"))
    assert not tax.is_intent_path(FolderPath.from_string("random/x"))


def test_plan_defaults_and_construction() -> None:
    """Given a Plan, When built, Then tuples default empty and hold values."""
    empty = Plan()
    assert empty.moves == () and empty.learned_rules == ()
    bm = _bm("https://example.com/a", FolderPath.from_string("work"))
    move = Assignment(
        bookmark=bm,
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
        confidence=1.0,
        via="rule",
    )
    dg = DedupeGroup(kept=bm, dropped=())
    rule = Rule(
        match=RuleMatch(domain="example.com"),
        folder=FolderPath.from_string("work"),
    )
    plan = Plan(moves=(move,), dedupes=(dg,), learned_rules=(rule,))
    assert plan.moves[0].via == "rule"
    assert plan.dedupes[0].kept is bm
    assert plan.learned_rules[0].source == "human"
