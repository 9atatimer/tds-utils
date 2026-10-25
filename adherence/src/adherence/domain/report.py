"""domain/report.py -- a run's outcome.

The checks that ran and every finding each produced (DESIGN.ARCH-
ADHERENCE.md, Measurement). Presenters shape it; it derives no number
from the findings.
"""

from __future__ import annotations

from dataclasses import dataclass

from adherence.domain.finding import Finding

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    """One run's findings. A run the suite could not perform is not run and
    carries the reason; it holds nothing else, so it never reads as a pass."""

    findings: tuple[Finding, ...] = ()
    not_run_reason: str | None = None

    @classmethod
    def not_run(cls, reason: str) -> Report:
        """The Report of a run that could not be performed, naming why."""
        return cls(not_run_reason=reason)
