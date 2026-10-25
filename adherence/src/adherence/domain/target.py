"""domain/target.py -- what a run reads: a Base or a Head.

A Base is the revision a change is judged against; a Head is what a
change produces, a revision, a working tree or a staged index
(DESIGN.ARCH-ADHERENCE.md, Domain Language).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class HeadKind(enum.Enum):
    """The three forms a Head takes."""

    REVISION = "revision"
    WORKING_TREE = "working tree"
    STAGED_INDEX = "staged index"


@dataclass(frozen=True, slots=True)
class Base:
    """The revision a change is judged against."""

    revision: str

    def __post_init__(self) -> None:
        if not self.revision:
            raise ValueError("a Base names a revision")


@dataclass(frozen=True, slots=True)
class Head:
    """What a change produces. Carries a revision exactly when it is one."""

    kind: HeadKind
    revision: str | None = None

    def __post_init__(self) -> None:
        if (self.kind is HeadKind.REVISION) != bool(self.revision):
            raise ValueError("a Head carries a revision exactly when it is one")

    @classmethod
    def at_revision(cls, revision: str) -> Head:
        return cls(HeadKind.REVISION, revision)

    @classmethod
    def working_tree(cls) -> Head:
        return cls(HeadKind.WORKING_TREE)

    @classmethod
    def staged_index(cls) -> Head:
        return cls(HeadKind.STAGED_INDEX)
