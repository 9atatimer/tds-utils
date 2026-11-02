"""domain/checks/run.py -- every target-level check over one CodeModel.

The checks implemented so far, by catalog name; measure calls run_checks
once per target.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from adherence.domain.checks import hexagonal, layered
from adherence.domain.checks.outcome import CheckFunction
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Finding
from adherence.domain.model import (
    CodeLanguage,
    CodeModel,
    UnitKind,
    language_of,
    without,
)
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG, Check, CheckKind, Quality
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

TARGET_CHECKS: Mapping[str, CheckFunction] = {
    "Grep": hexagonal.grep,
    "Arrow": hexagonal.arrow,
    "Swap": hexagonal.swap,
    "Change": hexagonal.change,
    "Trace": layered.trace,
    "Purity": layered.purity,
    "Wiring": layered.wiring,
    "Anatomy": layered.anatomy,
}
CHANGE_LEVEL = "a change-level check: it runs when a change is judged"
NOT_IN_SUITE = "not implemented in this suite version"
NO_JUDGE_YET = "a judged check: none is implemented in this suite version"
# The checks each language's model is complete enough for, for a language
# whose model holds only some facts (task-070); a language not named here
# is read by every check. Any other check runs without that language's
# files and reports each file it skipped (DESIGN.ARCH-ADHERENCE.md, G11).
# Complexity is absent for shell until a complexity adapter shows it
# covers shell (task-070: "only where lizard covers the language").
READ_BY: Mapping[str, frozenset[str]] = {
    CodeLanguage.SHELL.value: frozenset({"Anatomy", "Stub", "Dependency"}),
}

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


def reads(check: Check, path: str) -> bool:
    """Whether the check reads the language a file is written in."""
    language = language_of(path)
    if language is None or language not in READ_BY:
        return True
    return check.name in READ_BY[language]


def unread_by(check: Check, model: CodeModel) -> tuple[str, ...]:
    """Every file whose language the check does not read."""
    return tuple(
        u.path
        for u in model.units
        if u.kind is UnitKind.FILE and not reads(check, u.path)
    )


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
    # A file in no layer is already coverage (domain/coverage, UNASSIGNED).
    layered = {u.path for u in model.units if u.layer is not None}
    for check in CATALOG:
        run = TARGET_CHECKS.get(check.name)
        if run is None:
            coverage.append(_not_run(check))
            continue
        unread = unread_by(check, model)
        outcome = run(without(model, unread), declaration, records, parameters)
        if outcome.ran:
            ran.append(check)
            coverage.extend(
                Coverage(
                    f"does not read {language_of(path)}", check=check.name, path=path
                )
                for path in unread
                if path in layered
            )
        findings.extend(outcome.findings)
        coverage.extend(outcome.coverage)
    return Checked(tuple(ran), tuple(findings), tuple(coverage))
