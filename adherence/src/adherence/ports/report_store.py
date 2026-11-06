"""ports/report_store.py -- ReportStore: where reports persist and are read back.

A local file cache on the laptop, the warehouse with the file cache behind
it in CI, and a fake (ARCHITECTURE.ARCH-ADHERENCE.md, Seams). A cache keyed
by report identity and a ledger, never the authority: a miss measures
again. `get` takes the Deadline; `put` runs after the verdict and does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.report import Recorded, Report


@dataclass(frozen=True, slots=True)
class StoreMiss:
    """No report kept under that key, with why."""

    reason: str


class ReportStore(Protocol):
    def get(
        self, repository: str, revision: str, identity: str, deadline: Deadline | None
    ) -> Report | StoreMiss | TimedOut:
        """The report kept for the repository at the revision under the
        identity's digest."""
        ...

    def put(self, report: Report) -> Recorded:
        """Keep the report, under its repository, its revision and its
        identity; whether it held, and why not."""
        ...
