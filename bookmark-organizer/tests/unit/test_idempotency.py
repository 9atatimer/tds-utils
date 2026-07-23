"""Property tests for planner determinism and idempotency."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from orgmarks.domain.model import (
    Assignment,
    Bookmark,
    BookmarkTree,
    Folder,
    FolderPath,
)
from orgmarks.domain.planner import build_organized_tree
from orgmarks.domain.taxonomy import Intent, Taxonomy

_INTENTS = ("work", "fun")
_REFS = ("technical/dev", "culture/news", "technical/misc")

_TAX = Taxonomy(
    version=1,
    intents=(Intent(name="work"), Intent(name="fun")),
    pins=(),
    rules=(),
    reference_root=FolderPath.from_string("other/Reference"),
    triage_folder="_triage",
    max_umbrella_links=3,
)


@st.composite
def _assignments(draw: st.DrawFn) -> tuple[BookmarkTree, list[Assignment]]:
    n = draw(st.integers(min_value=1, max_value=12))
    marks: list[Bookmark] = []
    assignments: list[Assignment] = []
    for i in range(n):
        url = f"https://example.com/{i}"
        bm = Bookmark(
            url=url,
            title=f"t{i}",
            add_date=i + 1,
            source_path=FolderPath.from_string("bookmarks_bar"),
        )
        marks.append(bm)
        intent = draw(st.sampled_from(_INTENTS))
        leaf = draw(st.sampled_from(("dev", "hn", "misc")))
        ref = draw(st.sampled_from(_REFS))
        assignments.append(
            Assignment(
                bookmark=bm,
                folder=FolderPath.from_string(f"bookmarks_bar/{intent}/{leaf}"),
                ref=FolderPath.from_string(ref),
                confidence=1.0,
                via="rule",
            )
        )
    bar = Folder(name="bookmarks_bar", bookmarks=tuple(marks))
    return BookmarkTree(roots=(("bookmarks_bar", bar),)), assignments


@given(_assignments())
def test_build_is_deterministic(
    case: tuple[BookmarkTree, list[Assignment]],
) -> None:
    """Given the same inputs, When built twice, Then the trees are identical."""
    tree, assignments = case
    first = build_organized_tree(tree, _TAX, assignments)
    second = build_organized_tree(tree, _TAX, assignments)
    assert first == second


@given(_assignments())
def test_losslessness_and_exhaustiveness_hold(
    case: tuple[BookmarkTree, list[Assignment]],
) -> None:
    """Given any assignment set, When built, Then both URL invariants hold."""
    tree, assignments = case
    organized = build_organized_tree(tree, _TAX, assignments)
    all_urls = {a.bookmark.url for a in assignments}
    ref_root = _TAX.reference_root

    outside: set[str] = set()
    under: set[str] = set()

    def walk(folder: Folder, path: FolderPath) -> None:
        if path == ref_root:
            under.update(b.url for b in folder.iter_bookmarks())
            return
        outside.update(b.url for b in folder.bookmarks)
        for sub in folder.subfolders:
            walk(sub, path.child(sub.name))

    for name, folder in organized.roots:
        walk(folder, FolderPath((name,)))

    assert outside == all_urls
    assert under == all_urls
