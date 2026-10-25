"""domain/report.py -- a run's outcome.

The checks that ran and every finding each produced (DESIGN.ARCH-
ADHERENCE.md, Measurement). Presenters shape it; it derives no number
from the findings.
"""

from __future__ import annotations

from dataclasses import dataclass

from adherence.domain.coverage import Coverage
from adherence.domain.finding import Finding, Notice
from adherence.domain.qualities import Check, Quality

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    """One run's outcome: the checks that ran, every finding each produced,
    the notices and the coverage. A run the suite could not perform is not run and
    carries the reason; it holds nothing else, so it never reads as a pass."""

    ran: tuple[Check, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[Notice, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    not_run_reason: str | None = None

    def ran_in(self, quality: Quality) -> tuple[Check, ...]:
        """The checks of one quality that ran, in catalog order."""
        return tuple(c for c in self.ran if c.quality is quality)

    def findings_of(self, quality: Quality) -> tuple[Finding, ...]:
        """Every finding the checks of one quality produced."""
        return tuple(f for f in self.findings if f.check.quality is quality)

    @classmethod
    def not_run(cls, reason: str) -> Report:
        """The Report of a run that could not be performed, naming why."""
        return cls(not_run_reason=reason)
