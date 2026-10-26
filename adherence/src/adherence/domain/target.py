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


@dataclass(frozen=True, slots=True)
class Rename:
    """A file the change moved: its path at the base and at the head."""

    old: str
    new: str


@dataclass(frozen=True, slots=True)
class ChangedPaths:
    """What a change did to the repository's files: the paths it created,
    deleted and modified, and the files it renamed."""

    created: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    renamed: tuple[Rename, ...] = ()


@dataclass(frozen=True, slots=True)
class Change:
    """A repository's head against its base. The entry point names the
    repository, the base and the head; judge_change completes `paths` from
    RepositoryPort.changed before the domain reads it."""

    repository: str
    base: Base
    head: Head
    paths: ChangedPaths = ChangedPaths()

    @property
    def created(self) -> tuple[str, ...]:
        return self.paths.created

    @property
    def deleted(self) -> tuple[str, ...]:
        return self.paths.deleted

    @property
    def renamed(self) -> tuple[Rename, ...]:
        return self.paths.renamed

    def touched(self) -> frozenset[str]:
        """Every head path the change created, modified or renamed into."""
        p = self.paths
        return frozenset((*p.created, *p.modified, *(r.new for r in p.renamed)))

    def at_head(self, path: str) -> str:
        """A base path as the head names it: through the renames."""
        return next((r.new for r in self.paths.renamed if r.old == path), path)
