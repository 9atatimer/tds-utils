"""domain/checks/outcome.py -- what one check returns, and its signature.

Every target-level check is `(CodeModel, Declaration, DesignRecords,
Parameters) -> CheckOutcome`, pure (ARCHITECTURE.ARCH-ADHERENCE.md,
Mechanism > Measurement).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Finding
from adherence.domain.model import CodeModel
from adherence.domain.parameters import Parameters
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

NEEDS_DECLARATION = "needs a declaration; the repository has none"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """The findings one check produced, and what it could not cover. A check
    that could not run at all says so with `ran` false and its coverage."""

    findings: tuple[Finding, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    ran: bool = True


CheckFunction = Callable[
    [CodeModel, Declaration, DesignRecords | RecordsUnavailable, Parameters],
    CheckOutcome,
]

# A Radar-true check reads the radar in the records' place.
RadarCheckFunction = Callable[
    [CodeModel, Declaration, Radar | RecordsUnavailable, Parameters],
    CheckOutcome,
]


# --- Pure helpers ------------------------------------------------------------


def undeclared(check: str) -> CheckOutcome:
    """The outcome of a check that needs a declaration the repository lacks."""
    return CheckOutcome(coverage=(Coverage(NEEDS_DECLARATION, check=check),), ran=False)
