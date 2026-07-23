"""Unit tests for the normalizer: dedupe, canonicalize, prune, invariants."""

from __future__ import annotations

from orgmarks.domain.model import Bookmark, BookmarkTree, Folder, FolderPath
from orgmarks.domain.normalizer import (
    canonicalize_for_compare,
    normalize,
)


def _bm(url: str, path: str, *, title: str = "", add_date: int = 0) -> Bookmark:
    p = FolderPath.from_string(path)
    return Bookmark(url=url, title=title or url, add_date=add_date, source_path=p)


def _tree(bar: Folder) -> BookmarkTree:
    return BookmarkTree(roots=(("bookmarks_bar", bar),))


def test_canonicalize_strips_tracking_and_trailing_slash() -> None:
    """Given tracking params, When canonicalized, Then they are removed."""
    a = canonicalize_for_compare("https://example.com/x/?utm_source=news&id=7")
    b = canonicalize_for_compare("https://example.com/x?id=7")
    assert a == b


def test_canonicalize_keeps_non_tracking_params() -> None:
    """Given a real query param, When canonicalized, Then it is kept."""
    assert "id=7" in canonicalize_for_compare("https://example.com/x?id=7")


def test_stored_url_is_never_rewritten() -> None:
    """Given a survivor, When deduped, Then its url is the original string."""
    bar = Folder(
        name="bookmarks_bar",
        bookmarks=(
            _bm("https://example.com/a?utm_source=x", "bookmarks_bar", add_date=50),
            _bm("https://example.com/a", "bookmarks_bar", add_date=90),
        ),
    )
    result = normalize(_tree(bar), pins=())
    survivors = result.tree.root("bookmarks_bar").bookmarks
    assert len(survivors) == 1
    assert survivors[0].url == "https://example.com/a?utm_source=x"


def test_dedupe_keeps_oldest_add_date_and_best_title() -> None:
    """Given dupes, When deduped, Then oldest date and longest real title win."""
    bar = Folder(
        name="bookmarks_bar",
        bookmarks=(
            _bm("https://example.com/a", "bookmarks_bar", title="A", add_date=90),
            _bm(
                "https://example.com/a",
                "bookmarks_bar",
                title="A long descriptive title",
                add_date=40,
            ),
        ),
    )
    result = normalize(_tree(bar), pins=())
    survivor = result.tree.root("bookmarks_bar").bookmarks[0]
    assert survivor.add_date == 40
    assert survivor.title == "A long descriptive title"
    assert len(result.dedupes) == 1
    assert len(result.dedupes[0].dropped) == 1


def test_same_url_in_different_folders_is_preserved() -> None:
    """Given a url in two folders, When normalized, Then both copies remain."""
    sub = Folder(
        name="Sub",
        bookmarks=(_bm("https://example.com/a", "bookmarks_bar/Sub"),),
    )
    bar = Folder(
        name="bookmarks_bar",
        subfolders=(sub,),
        bookmarks=(_bm("https://example.com/a", "bookmarks_bar"),),
    )
    result = normalize(_tree(bar), pins=())
    assert result.tree.urls().count("https://example.com/a") == 2
    assert len(result.cross_folder_dups) == 1


def test_per_folder_uniqueness_invariant_holds() -> None:
    """Given dupes in one folder, When normalized, Then no folder repeats a url."""
    bar = Folder(
        name="bookmarks_bar",
        bookmarks=(
            _bm("https://example.com/a/", "bookmarks_bar"),
            _bm("https://example.com/a", "bookmarks_bar"),
            _bm("https://example.com/b", "bookmarks_bar"),
        ),
    )
    result = normalize(_tree(bar), pins=())

    def _folder_ok(folder: Folder) -> bool:
        keys = [canonicalize_for_compare(b.url) for b in folder.bookmarks]
        if len(keys) != len(set(keys)):
            return False
        return all(_folder_ok(s) for s in folder.subfolders)

    assert _folder_ok(result.tree.root("bookmarks_bar"))


def test_empty_folder_is_pruned() -> None:
    """Given an empty subfolder, When normalized, Then it is pruned + reported."""
    empty = Folder(name="Empty")
    bar = Folder(name="bookmarks_bar", subfolders=(empty,))
    result = normalize(_tree(bar), pins=())
    assert result.tree.root("bookmarks_bar").subfolders == ()
    assert FolderPath.from_string("bookmarks_bar/Empty") in result.pruned


def test_pinned_subtree_keeps_duplicates_verbatim() -> None:
    """Given dupes under a pin, When normalized, Then they are untouched."""
    pinned = Folder(
        name="Daily",
        bookmarks=(
            _bm("https://example.com/a", "bookmarks_bar/Daily"),
            _bm("https://example.com/a", "bookmarks_bar/Daily"),
        ),
    )
    bar = Folder(name="bookmarks_bar", subfolders=(pinned,))
    pins = (FolderPath.from_string("bookmarks_bar/Daily"),)
    result = normalize(_tree(bar), pins=pins)
    daily = result.tree.root("bookmarks_bar").subfolders[0]
    assert len(daily.bookmarks) == 2
    assert result.dedupes == ()
