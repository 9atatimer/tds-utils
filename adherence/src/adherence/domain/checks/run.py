"""domain/checks/run.py -- every target-level check over one CodeModel.

The checks implemented so far, by catalog name; measure calls run_checks
once per target.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from adherence.domain.checks import (
    behavior,
    complete,
    composable,
    ddd,
    hexagonal,
    injectable,
    layered,
    radar,
)
from adherence.domain.checks.outcome import CheckFunction, RadarCheckFunction
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Finding
from adherence.domain.model import CodeModel
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG, Check, CheckKind, Quality
from adherence.domain.questions import Ask
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

TARGET_CHECKS: Mapping[str, CheckFunction] = {
    "Grep": hexagonal.grep,
    "Arrow": hexagonal.arrow,
    "Swap": hexagonal.swap,
    "Change": hexagonal.change,
    "Stub": complete.stub,
    "Complexity": complete.complexity,
    "Duplication": complete.duplication,
    "Real assertion": behavior.real_assertion,
    "Public surface": behavior.public_surface,
    "Kept test": behavior.kept_test,
    "Then asserted": behavior.then_asserted,
    "No nesting": composable.no_nesting,
    "Helpers take values": composable.helpers_take_values,
    "Values in and out": composable.values_in_and_out,
    "Ports as keywords": injectable.ports_as_keywords,
    "No self-wiring": injectable.no_self_wiring,
    "No reach": injectable.no_reach,
    "Language": ddd.language,
    "Boundary": ddd.boundary,
    "Anemic": ddd.anemic,
    "Decision": ddd.decision,
    "Trace": layered.trace,
    "Purity": layered.purity,
    "Wiring": layered.wiring,
    "Anatomy": layered.anatomy,
    "Two jobs": layered.two_jobs,
}
RADAR_CHECKS: Mapping[str, RadarCheckFunction] = {
    "Dependency": radar.dependency,
    "Edge only": radar.edge_only,
}
NO_RADAR = RecordsUnavailable("no radar was read")
CHANGE_LEVEL = "a change-level check: it runs when a change is judged"
NOT_IN_SUITE = "not implemented in this suite version"
NO_JUDGE_YET = "a judged check: none is implemented in this suite version"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Checked:
    """What the target-level checks did: the checks that ran, their
    findings, the questions they put to the judge, and every check that did
    not run, with why."""

    ran: tuple[Check, ...]
    findings: tuple[Finding, ...]
    coverage: tuple[Coverage, ...]
    questions: tuple[Ask, ...] = ()


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
    *,
    radar: Radar | RecordsUnavailable = NO_RADAR,
) -> Checked:
    """Every implemented check over the model, in catalog order; every
    other check is coverage. The Radar-true checks read the radar."""
    ran: list[Check] = []
    findings: list[Finding] = []
    coverage: list[Coverage] = []
    questions: list[Ask] = []
    for check in CATALOG:
        run = TARGET_CHECKS.get(check.name)
        on_radar = RADAR_CHECKS.get(check.name)
        if run is not None:
            outcome = run(model, declaration, records, parameters)
        elif on_radar is not None:
            outcome = on_radar(model, declaration, radar, parameters)
        else:
            coverage.append(_not_run(check))
            continue
        if outcome.ran:
            ran.append(check)
        findings.extend(outcome.findings)
        coverage.extend(outcome.coverage)
        questions.extend(outcome.questions)
    return Checked(tuple(ran), tuple(findings), tuple(coverage), tuple(questions))
