"""ports/repository.py -- RepositoryPort: where files and revisions come from.

The working tree, the staged index, or a revision (ARCHITECTURE.ARCH-
ADHERENCE.md, Seams). Every method takes the Deadline. A path the adapter
will not hand over (a symbolic link, a path outside the root) is Refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.target import Base, ChangedPaths, Head


@dataclass(frozen=True, slots=True)
class Absent:
    """No file at that path in that target."""

    path: str


@dataclass(frozen=True, slots=True)
class Refused:
    """A path the repository will not hand over, with the reason."""

    path: str
    reason: str


class RepositoryPort(Protocol):
    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent | Refused | TimedOut:
        """The bytes at path in the target."""
        ...

    def tree(
        self, at: Base | Head, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        """Every file path the target holds, sorted; Refused, for the root,
        when the target cannot be listed."""
        ...

    def changed(
        self, base: Base, head: Head, deadline: Deadline | None
    ) -> ChangedPaths | Refused | TimedOut:
        """The paths the head created, deleted and modified against the
        base, each sorted; Refused, for the root, when they cannot be told."""
        ...
