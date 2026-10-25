"""ports/repository.py -- RepositoryPort: where files and revisions come from.

The working tree, the staged index, or a revision (ARCHITECTURE.ARCH-
ADHERENCE.md, Seams). Every method takes the Deadline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from adherence.domain.deadline import Deadline
from adherence.domain.target import Base, Head


@dataclass(frozen=True, slots=True)
class Absent:
    """No file at that path in that target."""

    path: str


class RepositoryPort(Protocol):
    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent:
        """The bytes at path in the target."""
        ...
