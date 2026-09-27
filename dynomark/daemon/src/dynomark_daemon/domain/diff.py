"""Proposed tree changes (audit and rebuild) and their items."""

from dataclasses import dataclass
from enum import StrEnum

from dynomark_daemon.domain.batch import Operation
from dynomark_daemon.domain.ids import BatchId, DiffId, ItemId


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


@dataclass(frozen=True, slots=True)
class DiffProposal:
    """One item the completion model proposes, before ids are minted."""

    action: DiffAction
    description: str
    operations: tuple[Operation, ...]
