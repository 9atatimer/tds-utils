"""adapters/tiered_store.py -- ReportStore composing the warehouse and the file cache.

ci's store (ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Where it runs):
`get` reads the warehouse's lookup key and nothing else, so the runner's
file cache -- which a pull request's run may have written on a shared
runner -- never keys a base; `put` writes the warehouse and the file
cache, and holds only when both did. Until the warehouse is provisioned
(tds-internal Issue#276) the composition root passes `Unprovisioned`: the
report is kept in the file cache alone, no base is read back, so the base
is measured again, and the notice says so. A write failure never changes
the verdict; it rides on Recorded.
"""

from __future__ import annotations

from dataclasses import dataclass

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.finding import Notice
from adherence.domain.report import Recorded, Report
from adherence.ports.report_store import ReportStore, StoreMiss

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Unprovisioned:
    """No warehouse to bind, and why."""

    reason: str


# --- Pure helpers ------------------------------------------------------------


def _joined(*notices: Notice | None) -> Notice | None:
    """One notice carrying every failure's message, or none."""
    messages = [n.message for n in notices if n is not None]
    return Notice("; ".join(messages)) if messages else None


# --- Adapter -----------------------------------------------------------------


class TieredReportStore:
    """ReportStore over `warehouse` for reads and writes, with `cache`
    written beside it and never read."""

    def __init__(
        self, *, warehouse: ReportStore | Unprovisioned, cache: ReportStore
    ) -> None:
        self._warehouse = warehouse
        self._cache = cache

    def get(
        self, repository: str, revision: str, identity: str, deadline: Deadline | None
    ) -> Report | StoreMiss | TimedOut:
        if isinstance(self._warehouse, Unprovisioned):
            return StoreMiss(
                f"no base is read back: {self._warehouse.reason}; the runner's "
                "file cache never keys a base"
            )
        return self._warehouse.get(repository, revision, identity, deadline)

    def put(self, report: Report) -> Recorded:
        cached = self._cache.put(report)
        if isinstance(self._warehouse, Unprovisioned):
            only = Notice(
                "report kept in the runner's file cache only, not in the "
                f"warehouse: {self._warehouse.reason}"
            )
            return Recorded(False, _joined(only, cached.notice))
        ledgered = self._warehouse.put(report)
        return Recorded(
            ledgered.kept and cached.kept, _joined(ledgered.notice, cached.notice)
        )
