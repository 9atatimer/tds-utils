"""ports/records.py -- RecordsPort: how design records are read at a target.

A markdown adapter over RepositoryPort and a fake (ARCHITECTURE.ARCH-
ADHERENCE.md, Seams); the records are read at the revision of the code
they are compared against, from the paths the declaration names.
"""

from __future__ import annotations

from typing import Protocol

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable
from adherence.domain.target import Base, Head


class RecordsPort(Protocol):
    def records(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> DesignRecords | RecordsUnavailable | TimedOut:
        """The approved design records the declaration names, at the target."""
        ...

    def radar(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> Radar | RecordsUnavailable | TimedOut:
        """The tech radar the declaration names, at the target."""
        ...
