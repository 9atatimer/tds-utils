"""The TreeOutline (DYNOMARK.DESIGN.md, Ubiquitous language: "the folder
skeleton of the owned subtree with pin/lock flags and per-folder item
counts; no URLs"), derived from the latest tree snapshot. Contract v1:
marker folders are excluded from the outline (Writer marker)."""

from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.tree import FolderFlags, OutlineFolder, outline_of
from tests._factories import make_node, make_path, make_tree

TREE = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("14", "11", "Rust"),
    make_node("15", "11", "dynomark-writer:mbp", index=1),
    make_node("20", "14", "Tokio", url="https://tokio.rs/"),
    make_node("21", "14", "Async", index=1),
    make_node("30", "10", "Saved", url="https://example.org/"),
)


def test_outline_holds_the_dynomark_folders_with_flags_and_item_counts() -> None:
    """Given a tree and a lock on one folder, When the outline is derived, Then
    it holds exactly the Dynomark folders (root included, marker and Follow Up
    excluded) with their flags and bookmark counts."""
    flags = {NodeId("14"): FolderFlags(pinned=False, locked=True)}

    outline = outline_of(TREE, make_path("Dynomark"), flags)

    assert outline.root == make_path("Dynomark")
    assert set(outline.folders) == {
        OutlineFolder(NodeId("11"), make_path("Dynomark"), False, False, 0),
        OutlineFolder(NodeId("14"), make_path("Dynomark", "Rust"), False, True, 1),
        OutlineFolder(
            NodeId("21"), make_path("Dynomark", "Rust", "Async"), False, False, 0
        ),
    }


def test_outline_of_a_tree_without_dynomark_is_empty() -> None:
    """Given a tree with no Dynomark folder, When the outline is derived, Then it
    has no folders (a fresh tree: file creates the root)."""
    outline = outline_of(make_tree(), make_path("Dynomark"), {})

    assert outline.folders == ()
