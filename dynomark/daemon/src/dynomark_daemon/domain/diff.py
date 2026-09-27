"""Proposed tree changes (audit and rebuild), the rules an item keeps, and
the batch an accepted item becomes (DYNOMARK.DESIGN.md: glossary
``pinned``, ``locked``, ``TreeDiff``; Multi-device policy; Goal 8)."""

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Self

from dynomark_daemon.domain.batch import (
    Expect,
    OpCreate,
    OpCreateFolder,
    Operation,
    OpMove,
    OpRemove,
    WriteBatch,
    admit,
    outside_roots,
    plan_inverse,
)
from dynomark_daemon.domain.bookmark import is_fetchable
from dynomark_daemon.domain.ids import BatchId, DiffId, ItemId
from dynomark_daemon.domain.tree import (
    WRITER_MARKER_PREFIX,
    FolderPath,
    OutlineFolder,
    OwnedRoots,
    TreeOutline,
)

MAX_ITEM_OPERATIONS: Final = 100
"""Operations per ``DiffItem`` (contract v1, Size limits)."""
MAX_DESCRIPTION: Final = 4096
"""A ``DiffItem`` description, in code points."""


class DiffKind(StrEnum):
    AUDIT = "audit"
    REBUILD = "rebuild"


class DiffAction(StrEnum):
    ADD = "add"
    MOVE = "move"
    MERGE = "merge"


@dataclass(frozen=True, slots=True)
class DiffItem:
    """One line of a diff; accepted when ``accepted_at`` is recorded."""

    item_id: ItemId
    diff_id: DiffId
    action: DiffAction
    description: str
    operations: tuple[Operation, ...]
    accepted_at: int | None = None
    batch_id: BatchId | None = None


@dataclass(frozen=True, slots=True)
class TreeDiff:
    """A proposed set of adds, moves and merges of one ``DiffKind``."""

    diff_id: DiffId
    kind: DiffKind
    proposed_at: int
    items: tuple[DiffItem, ...]

    def with_id(self, diff_id: DiffId) -> Self:
        """The same diff under ``diff_id``, its items pointing at it."""
        items = tuple(replace(item, diff_id=diff_id) for item in self.items)
        return replace(self, diff_id=diff_id, items=items)


@dataclass(frozen=True, slots=True)
class DiffProposal:
    """One item the completion model proposes, before ids are minted."""

    action: DiffAction
    description: str
    operations: tuple[Operation, ...]


# --- The rules an item keeps ---


@dataclass(frozen=True, slots=True)
class DiffScope:
    """What a diff was proposed from: its kind, the ``Dynomark`` outline (with
    flags), the user's own bar outline, and the owned roots."""

    kind: DiffKind
    outline: TreeOutline
    own_bar: TreeOutline
    roots: OwnedRoots

    def movable(self) -> dict[str, OutlineFolder]:
        """The folders an item of this kind may move, by node id: rebuild only
        the owned tree's, audit also the user's bar's."""
        outlines: tuple[TreeOutline, ...] = (self.outline,)
        if self.kind is DiffKind.AUDIT:
            outlines = (self.outline, self.own_bar)
        return {f.node_id: f for outline in outlines for f in outline.folders}

    def is_locked(self, path: FolderPath) -> bool:
        return self.outline.is_locked(path) or self.own_bar.is_locked(path)


def _has_marker(path: FolderPath) -> bool:
    return any(name.startswith(WRITER_MARKER_PREFIX) for name in path.names)


def _target_violations(target: FolderPath, scope: DiffScope) -> Iterator[str]:
    if scope.is_locked(target):
        yield f"{list(target.names)} is locked"
    if _has_marker(target):
        yield f"{list(target.names)} is a writer marker"


def _node_violations(
    node_id: str, scope: DiffScope, folders: dict[str, OutlineFolder]
) -> Iterator[str]:
    folder = folders.get(node_id)
    if folder is None:
        yield f"node {node_id} is no folder this diff may move"
        return
    if not folder.path.names or scope.roots.is_root(folder.path):
        yield f"{list(folder.path.names)} is a root"
    if folder.pinned:
        yield f"{list(folder.path.names)} is pinned"
    if scope.is_locked(folder.path):
        yield f"{list(folder.path.names)} is locked"


def _op_violations(
    op: Operation, scope: DiffScope, folders: dict[str, OutlineFolder]
) -> Iterator[str]:
    match op:
        case OpCreateFolder():
            yield from _target_violations(op.parent.child(op.title), scope)
        case OpCreate():
            yield from _target_violations(op.parent, scope)
            if not is_fetchable(op.url):
                yield f"op {op.index} creates a non-http(s) bookmark"
        case OpMove():
            yield from _node_violations(op.node_id, scope, folders)
            yield from _target_violations(op.to, scope)
            folder = folders.get(op.node_id)
            if folder is not None and op.to.is_inside(folder.path):
                yield f"op {op.index} moves a folder into itself"
        case OpRemove():
            yield from _node_violations(op.node_id, scope, folders)


def violations(operations: Sequence[Operation], scope: DiffScope) -> tuple[str, ...]:
    """Why these operations may not be one ``DiffItem`` of ``scope``: a pinned
    folder moved or removed; a locked folder (or anything inside one)
    touched; a node moved that is no folder the outlines hold, or a root; a
    folder moved into itself; a writer marker named; a non-http(s) bookmark
    created; a rebuild leaving the owned roots (only audit items cross)."""
    folders = scope.movable()
    found = [
        reason for op in operations for reason in _op_violations(op, scope, folders)
    ]
    if scope.kind is DiffKind.REBUILD:
        folder_paths = {f.node_id: f.path for f in folders.values()}
        sources = [
            folder_paths[op.node_id]
            for op in operations
            if isinstance(op, OpMove | OpRemove) and op.node_id in folder_paths
        ]
        outside = outside_roots(tuple(operations), scope.roots)
        if outside or not all(scope.roots.contains(p) for p in sources):
            found.append("a rebuild item leaves the owned roots")
    return tuple(found)


def numbered(operations: Sequence[Operation]) -> tuple[Operation, ...]:
    """The operations with ``index`` == position."""
    return tuple(replace(op, index=i) for i, op in enumerate(operations))


def vet(proposal: DiffProposal, scope: DiffScope) -> DiffProposal | None:
    """The proposal as an item may hold it -- operations numbered, the
    description stripped and capped -- or ``None`` when it breaks a rule or
    has no description or 0 or more than 100 operations."""
    description = proposal.description.strip()[:MAX_DESCRIPTION]
    count = len(proposal.operations)
    if not description or not 1 <= count <= MAX_ITEM_OPERATIONS:
        return None
    operations = numbered(proposal.operations)
    if violations(operations, scope):
        return None
    return DiffProposal(
        action=proposal.action, description=description, operations=operations
    )


# --- Building operations from outline paths (for a completion adapter) ---


def _folder_at(
    path: FolderPath, outlines: Sequence[TreeOutline]
) -> OutlineFolder | None:
    for outline in outlines:
        found = outline.folder_at(path)
        if found is not None:
            return found
    return None


def folder_add(
    path: FolderPath, outlines: Sequence[TreeOutline]
) -> tuple[Operation, ...]:
    """Create each level of ``path`` no outline holds, top down."""
    creates: list[Operation] = []
    for depth in range(1, len(path.names) + 1):
        if _folder_at(path.prefix(depth), outlines) is None:
            creates.append(
                OpCreateFolder(
                    index=len(creates),
                    parent=path.prefix(depth - 1),
                    title=path.names[depth - 1],
                )
            )
    return tuple(creates)


def folder_move(
    folder: OutlineFolder, to: FolderPath, outlines: Sequence[TreeOutline]
) -> tuple[Operation, ...] | None:
    """Create the missing levels of ``to``, then move ``folder`` into it,
    expecting its current parent by id and path; ``None`` when no outline
    holds that parent."""
    parent_path = folder.path.prefix(len(folder.path.names) - 1)
    parent = _folder_at(parent_path, outlines) if folder.path.names else None
    if parent is None:
        return None
    creates = folder_add(to, outlines)
    move = OpMove(
        index=len(creates),
        node_id=folder.node_id,
        to=to,
        expect=Expect(parent_id=parent.node_id, parent_path=parent_path),
    )
    return (*creates, move)


# --- The batch an accepted item becomes (Goal 8) ---


class NotAccepted(Exception):
    """An item without ``accepted_at`` never becomes a batch."""


def item_batch_id(item_id: ItemId) -> BatchId:
    """The one batch an item becomes: a function of the item, so accepting it
    again finds the same batch (contract v1: ``diff.accept`` is idempotent
    on ``item_id``)."""
    digest = hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:40]
    return BatchId(f"batch-{digest}")


def item_batch(item: DiffItem, kind: DiffKind, roots: OwnedRoots) -> WriteBatch:
    """The batch realizing an accepted item: its operations, their inverse,
    and the item's reference. An audit item may cross the ``OwnedRoots``
    boundary (the item is the exception); a rebuild item may not.

    Raises:
        NotAccepted: ``accepted_at`` is unset.
        OutsideOwnedRoots: a rebuild item leaves the owned roots.
    """
    if item.accepted_at is None:
        raise NotAccepted(f"item {item.item_id} is not accepted")
    if kind is DiffKind.REBUILD:
        admit(item.operations, roots)
    return WriteBatch(
        batch_id=item_batch_id(item.item_id),
        operations=item.operations,
        inverse=plan_inverse(item.operations, roots),
        diff_item_id=item.item_id,
    )
