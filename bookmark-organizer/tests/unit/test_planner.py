"""Unit tests for the planner: intent tree, Reference index, invariants."""

from __future__ import annotations

import pytest

from orgmarks.domain.errors import DomainError
from orgmarks.domain.model import (
    Assignment,
    Bookmark,
    BookmarkTree,
    Folder,
    FolderPath,
)
from orgmarks.domain.planner import build_organized_tree, build_plan
from orgmarks.domain.shape import check_shape
from orgmarks.domain.taxonomy import Intent, Taxonomy


def _bm(url: str, path: str = "bookmarks_bar", *, title: str = "t") -> Bookmark:
    return Bookmark(
        url=url, title=title, add_date=1, source_path=FolderPath.from_string(path)
    )


def _assign(bm: Bookmark, folder: str, ref: str, via: str = "rule") -> Assignment:
    return Assignment(
        bookmark=bm,
        folder=FolderPath.from_string(folder),
        ref=FolderPath.from_string(ref),
        confidence=1.0,
        via=via,  # type: ignore[arg-type]
    )


def _tax(**kw: object) -> Taxonomy:
    return Taxonomy(
        version=1,
        intents=(Intent(name="work"), Intent(name="fun")),
        pins=kw.get("pins", ()),  # type: ignore[arg-type]
        rules=(),
        reference_root=FolderPath.from_string("other/Reference"),
        triage_folder="_triage",
        max_umbrella_links=3,
    )


def _source_tree(bookmarks: list[Bookmark]) -> BookmarkTree:
    bar = Folder(name="bookmarks_bar", bookmarks=tuple(bookmarks))
    return BookmarkTree(roots=(("bookmarks_bar", bar),))


def _urls_excluding_reference(
    tree: BookmarkTree, reference_root: FolderPath
) -> set[str]:
    found: set[str] = set()

    def walk(folder: Folder, path: FolderPath) -> None:
        if path == reference_root:
            return
        found.update(b.url for b in folder.bookmarks)
        for sub in folder.subfolders:
            walk(sub, path.child(sub.name))

    for name, folder in tree.roots:
        walk(folder, FolderPath((name,)))
    return found


def _urls_under(tree: BookmarkTree, reference_root: FolderPath) -> set[str]:
    found: set[str] = set()

    def walk(folder: Folder, path: FolderPath) -> None:
        if path == reference_root:
            found.update(b.url for b in folder.iter_bookmarks())
            return
        for sub in folder.subfolders:
            walk(sub, path.child(sub.name))

    for name, folder in tree.roots:
        walk(folder, FolderPath((name,)))
    return found


def test_intent_folders_appear_in_declared_order_triage_last() -> None:
    """Given intents + triage, When organized, Then order is intents...triage."""
    tax = _tax()
    a = _bm("https://example.com/a")
    b = _bm("https://example.com/b")
    c = _bm("https://example.com/c")
    assignments = [
        _assign(c, "bookmarks_bar/_triage", "technical/misc", via="triage"),
        _assign(b, "bookmarks_bar/fun/games", "culture/games"),
        _assign(a, "bookmarks_bar/work/dev", "technical/dev"),
    ]
    tree = build_organized_tree(_source_tree([a, b, c]), tax, assignments)
    bar_children = [f.name for f in tree.root("bookmarks_bar").subfolders]
    assert bar_children == ["work", "fun", "_triage"]


def test_losslessness_every_url_outside_reference() -> None:
    """Given assignments, When organized, Then intent tree holds every url."""
    tax = _tax()
    marks = [_bm(f"https://example.com/{i}") for i in range(4)]
    assignments = [
        _assign(marks[0], "bookmarks_bar/work/dev", "technical/dev"),
        _assign(marks[1], "bookmarks_bar/work/dev", "technical/dev"),
        _assign(marks[2], "bookmarks_bar/fun/hn", "culture/news"),
        _assign(marks[3], "bookmarks_bar/_triage", "technical/misc", via="triage"),
    ]
    tree = build_organized_tree(_source_tree(marks), tax, assignments)
    outside = _urls_excluding_reference(tree, tax.reference_root)
    assert outside == {b.url for b in marks}


def test_reference_index_is_exhaustive() -> None:
    """Given assignments, When organized, Then Reference holds every url."""
    tax = _tax()
    marks = [_bm(f"https://example.com/{i}") for i in range(4)]
    assignments = [
        _assign(marks[0], "bookmarks_bar/work/dev", "technical/dev"),
        _assign(marks[1], "bookmarks_bar/fun/hn", "culture/news"),
        _assign(marks[2], "bookmarks_bar/fun/hn", "culture/news"),
        _assign(marks[3], "bookmarks_bar/_triage", "technical/misc", via="triage"),
    ]
    tree = build_organized_tree(_source_tree(marks), tax, assignments)
    assert _urls_under(tree, tax.reference_root) == {b.url for b in marks}


def test_shape_holds_on_every_non_pinned_hub() -> None:
    """Given a mixed hub, When organized, Then shape checks pass."""
    tax = _tax()
    root_link = _bm("https://work.example.com/", title="Work Root")
    deep = _bm("https://elsewhere.example.com/a/b/c", title="Deep")
    child = _bm("https://example.com/child")
    assignments = [
        _assign(root_link, "bookmarks_bar/work", "technical/root"),
        _assign(deep, "bookmarks_bar/work", "technical/deep"),
        _assign(child, "bookmarks_bar/work/dev", "technical/dev"),
    ]
    tree = build_organized_tree(
        _source_tree([root_link, deep, child]), tax, assignments
    )
    for _, folder in tree.roots:
        assert check_shape(folder, max_umbrella_links=3) == []


def test_pinned_subtree_is_exempt_from_shape() -> None:
    """Given a pin, When organized, Then its stranded links are not wrapped."""
    tax = _tax(pins=(FolderPath.from_string("bookmarks_bar/Daily"),))
    pinned_deep = _bm("https://elsewhere.example.com/a/b", title="Deep")
    sibling = _bm("https://example.com/other")
    assignments = [
        # A pin hub that also has a subfolder, plus a deep (stranded) link.
        _assign(pinned_deep, "bookmarks_bar/Daily", "technical/deep", via="pin"),
        _assign(sibling, "bookmarks_bar/Daily/Sub", "technical/misc", via="pin"),
    ]
    tree = build_organized_tree(_source_tree([pinned_deep, sibling]), tax, assignments)
    daily = next(f for f in tree.root("bookmarks_bar").subfolders if f.name == "Daily")
    # Not wrapped: the deep link stays a direct child of the pinned hub.
    assert pinned_deep.url in {b.url for b in daily.bookmarks}


def test_pinned_subtree_is_copied_verbatim_including_empty_folders() -> None:
    """Given a pin with an empty subfolder, When organized, Then it survives."""
    tax = _tax(pins=(FolderPath.from_string("bookmarks_bar/Daily"),))
    daily_bm = _bm("https://example.com/daily", "bookmarks_bar/Daily")
    # Input tree really contains the Daily folder, with an empty subfolder.
    daily = Folder(
        name="Daily",
        subfolders=(Folder(name="Empty", add_date=42),),
        bookmarks=(daily_bm,),
    )
    bar = Folder(name="bookmarks_bar", subfolders=(daily,))
    tree = BookmarkTree(roots=(("bookmarks_bar", bar),))
    assignments = [
        _assign(daily_bm, "bookmarks_bar/Daily", "technical/daily", via="pin")
    ]
    organized = build_organized_tree(tree, tax, assignments)
    out_daily = next(
        f for f in organized.root("bookmarks_bar").subfolders if f.name == "Daily"
    )
    # The empty folder and its metadata are preserved verbatim.
    empty = next(f for f in out_daily.subfolders if f.name == "Empty")
    assert empty.add_date == 42
    assert empty.bookmarks == ()
    # The pinned bookmark appears once in the intent tree (not duplicated).
    assert [b.url for b in out_daily.bookmarks] == ["https://example.com/daily"]


def test_non_pin_assignment_under_pin_raises_domain_error() -> None:
    """Given a non-pin assignment under a pin, When organized, Then it raises."""
    tax = _tax(pins=(FolderPath.from_string("bookmarks_bar/Daily"),))
    bm = _bm("https://example.com/x", "bookmarks_bar/Loose")
    bad = _assign(bm, "bookmarks_bar/Daily/sub", "technical/dev", via="rule")
    with pytest.raises(DomainError):
        build_organized_tree(_source_tree([bm]), tax, [bad])


def test_build_plan_records_moves_and_creates() -> None:
    """Given assignments, When planned, Then moves and folder creates appear."""
    tax = _tax()
    a = _bm("https://example.com/a")
    assignments = [_assign(a, "bookmarks_bar/work/dev", "technical/dev")]
    plan = build_plan(_source_tree([a]), tax, assignments)
    assert plan.moves == tuple(assignments)
    created = {str(op.path) for op in plan.folder_ops}  # type: ignore[union-attr]
    assert "bookmarks_bar/work/dev" in created
