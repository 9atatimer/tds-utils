"""Unit tests for skinny-tree shape invariants."""

from __future__ import annotations

from orgmarks.domain.model import Bookmark, Folder, FolderPath
from orgmarks.domain.shape import check_shape, enforce_shape, is_umbrella_link


def _bm(url: str, *, title: str = "t") -> Bookmark:
    return Bookmark(
        url=url, title=title, add_date=1, source_path=FolderPath.from_string("x")
    )


def test_umbrella_link_needs_shallow_path_and_matching_host() -> None:
    """Given a root-of-concept URL, When checked, Then it is an umbrella link."""
    assert is_umbrella_link(_bm("https://github.com/"), "GitHub")
    assert not is_umbrella_link(_bm("https://github.com/a/b/c"), "GitHub")
    assert not is_umbrella_link(_bm("https://example.com/"), "GitHub")


def test_leaf_folder_is_left_unchanged() -> None:
    """Given a leaf with several links, When enforced, Then it is unchanged."""
    leaf = Folder(name="Reading", bookmarks=(_bm("https://a.example.com/1"),))
    assert enforce_shape(leaf, max_umbrella_links=3) == leaf
    assert check_shape(leaf, max_umbrella_links=3) == []


def test_stranded_link_in_hub_is_wrapped() -> None:
    """Given a stranded link in a hub, When enforced, Then it is wrapped."""
    sub = Folder(name="Sub", bookmarks=(_bm("https://a.example.com/x"),))
    hub = Folder(
        name="work",
        subfolders=(sub,),
        bookmarks=(_bm("https://deep.example.com/a/b", title="Deep"),),
    )
    assert check_shape(hub, max_umbrella_links=3)  # flagged before
    fixed = enforce_shape(hub, max_umbrella_links=3)
    assert fixed.bookmarks == ()
    wrapper = next(f for f in fixed.subfolders if f.name == "Deep")
    assert wrapper.bookmarks[0].url == "https://deep.example.com/a/b"
    assert check_shape(fixed, max_umbrella_links=3) == []


def test_umbrella_links_capped_and_extras_wrapped() -> None:
    """Given too many umbrella links, When enforced, Then extras are wrapped."""
    links = tuple(
        _bm(f"https://work{i}.example.com/", title=f"Root {i}") for i in range(5)
    )
    hub = Folder(
        name="work",
        subfolders=(Folder(name="Sub"),),
        bookmarks=links,
    )
    fixed = enforce_shape(hub, max_umbrella_links=3)
    assert len(fixed.bookmarks) <= 3
    assert check_shape(fixed, max_umbrella_links=3) == []


def test_enforce_shape_is_idempotent() -> None:
    """Given a hub, When enforced twice, Then the second pass is a no-op."""
    hub = Folder(
        name="work",
        subfolders=(Folder(name="Sub", bookmarks=(_bm("https://a.example.com/1"),)),),
        bookmarks=(
            _bm("https://work.example.com/", title="Root"),
            _bm("https://deep.example.com/a/b", title="Deep"),
        ),
    )
    once = enforce_shape(hub, max_umbrella_links=3)
    twice = enforce_shape(once, max_umbrella_links=3)
    assert once == twice
