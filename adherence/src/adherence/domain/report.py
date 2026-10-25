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
    """One run's findings."""

    findings: tuple[Finding, ...] = ()
