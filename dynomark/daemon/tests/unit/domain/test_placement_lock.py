"""Behaviors row: Placement respects a lock (DYNOMARK.DESIGN.md, Behaviors and
Interfaces): "Given the fake completion names a locked folder, When placed,
Then the result is a sibling or new leaf, never inside it" -- over every
tree hypothesis draws, not one fixture (issue #423).

The folder that bars a choice is the outermost locked folder (or writer
marker) at or above it; the fallback is a sibling of that folder or a new
leaf under its parent, preferring the sibling most neighbours sit in.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.placement import (
    NoAdmissibleFolder,
    admit_folder,
    is_admissible,
    resolve_choice,
)
from dynomark_daemon.domain.tree import WRITER_MARKER_PREFIX, FolderPath, TreeOutline
from dynomark_daemon.testing.strategies import choices_in, locked_outlines


def _barrier(path: FolderPath, outline: TreeOutline) -> FolderPath | None:
    """The outermost locked folder or writer marker at or above ``path``."""
    for depth in range(len(outline.root.names), len(path.names) + 1):
        prefix = path.prefix(depth)
        folder = outline.folder_at(prefix)
        marker = depth > len(outline.root.names) and prefix.names[-1].startswith(
            WRITER_MARKER_PREFIX
        )
        if marker or (folder is not None and folder.locked):
            return prefix
    return None


@st.composite
def _cases(
    draw: st.DrawFn,
) -> tuple[TreeOutline, FolderPath, list[FolderPath]]:
    outline = draw(locked_outlines())
    choice = draw(choices_in(outline))
    folders = [f.path for f in outline.folders]
    neighbours = draw(st.lists(st.sampled_from(folders), max_size=5))
    return outline, choice, neighbours


@given(_cases())
def test_a_barred_choice_falls_back_to_a_sibling_or_a_new_leaf_beside_it(
    case: tuple[TreeOutline, FolderPath, list[FolderPath]],
) -> None:
    """Given any outline with locks, a choice and neighbours, When admitted,
    Then an admissible choice stands; a choice barred by a locked folder (or
    marker) lands beside that folder -- a sibling of it or a new leaf under
    its parent, never inside it -- preferring the admissible sibling most
    neighbours sit in; and only a locked Dynomark root admits nothing."""
    outline, choice, neighbours = case
    resolved = resolve_choice(choice, outline)
    assert resolved is not None
    barrier = _barrier(resolved, outline)

    if barrier == outline.root:
        with pytest.raises(NoAdmissibleFolder):
            admit_folder(choice, outline, neighbours)
        return
    result = admit_folder(choice, outline, neighbours)

    assert is_admissible(result, outline)
    if barrier is None:
        assert result == resolved
        return
    parent = barrier.prefix(len(barrier.names) - 1)
    assert not result.is_inside(barrier)
    assert result == parent or result.prefix(len(parent.names)) == parent
    assert len(result.names) <= len(parent.names) + 1
    siblings = [
        f.path
        for f in outline.children_of(parent)
        if f.path != barrier and is_admissible(f.path, outline)
    ]
    held = {s: sum(n.is_inside(s) for n in neighbours) for s in siblings}
    if any(held.values()):
        assert held.get(result, 0) == max(held.values())
