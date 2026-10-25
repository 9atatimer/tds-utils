"""domain/checks/run.py -- every target-level check over one CodeModel.

The checks implemented so far, by catalog name; measure calls run_checks
once per target.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from adherence.domain.checks import hexagonal
from adherence.domain.checks.outcome import CheckFunction
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Finding
from adherence.domain.model import CodeModel
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG, Check, CheckKind, Quality
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

TARGET_CHECKS: Mapping[str, CheckFunction] = {
    "Grep": hexagonal.grep,
    "Arrow": hexagonal.arrow,
}
CHANGE_LEVEL = "a change-level check: it runs when a change is judged"
NOT_IN_SUITE = "not implemented in this suite version"
NO_JUDGE_YET = "a judged check: none is implemented in this suite version"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Checked:
    """What the target-level checks did: the checks that ran, their
    findings, and every check that did not run, with why."""

    ran: tuple[Check, ...]
    findings: tuple[Finding, ...]
    coverage: tuple[Coverage, ...]


# --- Pure helpers ------------------------------------------------------------


def _not_run(check: Check) -> Coverage:
    """Why a check the suite has no function for did not run."""
    if check.quality is Quality.DECLARED:
        return Coverage(CHANGE_LEVEL, check=check.name)
    if check.kind is CheckKind.JUDGED:
        return Coverage(NO_JUDGE_YET, check=check.name)
    return Coverage(NOT_IN_SUITE, check=check.name)


def run_checks(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> Checked:
    """Every implemented check over the model, in catalog order; every
    other check is coverage."""
    ran: list[Check] = []
    findings: list[Finding] = []
    coverage: list[Coverage] = []
    for check in CATALOG:
        run = TARGET_CHECKS.get(check.name)
        if run is None:
            coverage.append(_not_run(check))
            continue
        outcome = run(model, declaration, records, parameters)
        ran.append(check)
        findings.extend(outcome.findings)
    return Checked(tuple(ran), tuple(findings), tuple(coverage))
