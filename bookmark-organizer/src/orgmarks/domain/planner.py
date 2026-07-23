"""Planner: turn assignments into the organized tree and the Plan.

Placement paths in ``Assignment.folder`` are ABSOLUTE (they begin with a root
name, e.g. ``bookmarks_bar/work/dev``); the pipeline is responsible for
rooting intent paths under the bar. The planner:

- reconstructs each bookmark at its assigned folder;
- keeps intent folders in the taxonomy's declared order, ``_triage`` last;
- leaves pinned subtrees exempt from shape enforcement (verbatim);
- rebuilds an exhaustive ``Reference`` index (a copy of every bookmark) under
  ``reference_root``, filed by ``Assignment.ref``.

Invariants enforced by construction: losslessness (every input URL appears in
the organized tree outside Reference), Reference exhaustiveness (every URL
appears under Reference), skinny-tree shape on non-pinned hubs, and
determinism (same assignments -> identical tree).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from orgmarks.domain.model import (
    Assignment,
    Bookmark,
    BookmarkTree,
    CreateFolder,
    DedupeGroup,
    Folder,
    FolderOp,
    FolderPath,
    Plan,
    RootName,
    Rule,
)
from orgmarks.domain.shape import enforce_local
from orgmarks.domain.taxonomy import Taxonomy


@dataclass(slots=True)
class _Node:
    """Mutable builder node keyed by child name, order-preserving."""

    name: str
    children: dict[str, _Node] = field(default_factory=dict)
    bookmarks: list[Bookmark] = field(default_factory=list)

    def child(self, name: str) -> _Node:
        node = self.children.get(name)
        if node is None:
            node = _Node(name=name)
            self.children[name] = node
        return node


def _insert(root: _Node, segments: Sequence[str], bookmark: Bookmark) -> None:
    node = root
    for seg in segments:
        node = node.child(seg)
    node.bookmarks.append(bookmark)


def _is_pinned(path: FolderPath, pins: Sequence[FolderPath]) -> bool:
    return any(path.is_under(pin) for pin in pins)


def _freeze(node: _Node, path: FolderPath, taxonomy: Taxonomy) -> Folder:
    subfolders = tuple(
        _freeze(child, path.child(child.name), taxonomy)
        for child in node.children.values()
    )
    folder = Folder(
        name=node.name, subfolders=subfolders, bookmarks=tuple(node.bookmarks)
    )
    if _is_pinned(path, taxonomy.pins):
        return folder
    return enforce_local(folder, max_umbrella_links=taxonomy.max_umbrella_links)


def _reorder_bar(node: _Node, taxonomy: Taxonomy) -> None:
    """Reorder the bar's children: intents (declared order), rest, triage last."""
    intents = taxonomy.intent_names()
    triage = taxonomy.triage_folder

    def rank(name: str) -> tuple[int, int]:
        if name in intents:
            return (0, intents.index(name))
        if name == triage:
            return (2, 0)
        return (1, 0)

    node.children = dict(sorted(node.children.items(), key=lambda kv: rank(kv[0])))


def build_organized_tree(
    tree: BookmarkTree, taxonomy: Taxonomy, assignments: Sequence[Assignment]
) -> BookmarkTree:
    """Build the organized BookmarkTree (intent tree + Reference index)."""
    roots: dict[str, _Node] = {}

    def root_node(name: str) -> _Node:
        node = roots.get(name)
        if node is None:
            node = _Node(name=name)
            roots[name] = node
        return node

    # Always materialize the bar and pre-seed intents in declared order.
    bar = root_node("bookmarks_bar")
    for intent in taxonomy.intent_names():
        bar.child(intent)

    # Intent placement (absolute paths; first segment is the root).
    for assignment in assignments:
        parts = assignment.folder.parts
        if not parts:
            continue
        _insert(root_node(parts[0]), parts[1:], assignment.bookmark)

    # Reference index: a copy of every bookmark under reference_root.
    ref_parts = taxonomy.reference_root.parts
    if ref_parts:
        ref_root = root_node(ref_parts[0])
        for assignment in assignments:
            segments = (*ref_parts[1:], *assignment.ref.parts)
            _insert(ref_root, segments, assignment.bookmark)

    _reorder_bar(bar, taxonomy)

    ordered_names: list[RootName] = ["bookmarks_bar", "other", "synced"]
    frozen: list[tuple[RootName, Folder]] = []
    for name in ordered_names:
        if name in roots:
            frozen.append((name, _freeze(roots[name], FolderPath((name,)), taxonomy)))
    return BookmarkTree(roots=tuple(frozen))


def _folder_paths(tree: BookmarkTree) -> set[FolderPath]:
    paths: set[FolderPath] = set()

    def walk(folder: Folder, path: FolderPath) -> None:
        for sub in folder.subfolders:
            child = path.child(sub.name)
            paths.add(child)
            walk(sub, child)

    for name, folder in tree.roots:
        walk(folder, FolderPath((name,)))
    return paths


def build_plan(
    tree: BookmarkTree,
    taxonomy: Taxonomy,
    assignments: Sequence[Assignment],
    dedupes: Sequence[DedupeGroup] = (),
    learned_rules: Sequence[Rule] = (),
) -> Plan:
    """Assemble the Plan: moves, dedupes, folder creates, and learned rules."""
    organized = build_organized_tree(tree, taxonomy, assignments)
    before = _folder_paths(tree)
    after = _folder_paths(organized)
    creates: tuple[FolderOp, ...] = tuple(
        CreateFolder(path=path)
        for path in sorted(after - before, key=lambda p: p.parts)
    )
    return Plan(
        moves=tuple(assignments),
        dedupes=tuple(dedupes),
        folder_ops=creates,
        learned_rules=tuple(learned_rules),
    )
