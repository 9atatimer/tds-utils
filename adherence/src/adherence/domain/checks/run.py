"""domain/checks/run.py -- every target-level check over one CodeModel.

The checks implemented so far, by catalog name; measure calls run_checks
once per target.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

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
from adherence.domain.checks.outcome import (
    CheckFunction,
    CheckOutcome,
    RadarCheckFunction,
)
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Finding
from adherence.domain.model import CodeModel, UnitKind, within
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG, Check, CheckKind, Quality
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
    "No nesting": composable.no_nesting,
    "Helpers take values": composable.helpers_take_values,
    "Values in and out": composable.values_in_and_out,
    "Ports as keywords": injectable.ports_as_keywords,
    "No self-wiring": injectable.no_self_wiring,
    "No reach": injectable.no_reach,
    "Language": ddd.language,
    "Boundary": ddd.boundary,
    "Anemic": ddd.anemic,
    "Trace": layered.trace,
    "Purity": layered.purity,
    "Wiring": layered.wiring,
    "Anatomy": layered.anatomy,
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


@dataclass(frozen=True, slots=True)
class _Inputs:
    """What every target-level check is given."""

    model: CodeModel
    declaration: Declaration
    records: DesignRecords | RecordsUnavailable
    parameters: Parameters
    radar: Radar | RecordsUnavailable
    checks: Mapping[str, CheckFunction]

    def over(self, model: CodeModel) -> _Inputs:
        return replace(self, model=model)


def _outcome(check: Check, given: _Inputs) -> CheckOutcome | None:
    """The check's outcome, or None when the suite has no function for it."""
    run = given.checks.get(check.name)
    if run is not None:
        return run(given.model, given.declaration, given.records, given.parameters)
    on_radar = RADAR_CHECKS.get(check.name)
    if on_radar is not None:
        return on_radar(given.model, given.declaration, given.radar, given.parameters)
    return None


def _raises(check: Check, given: _Inputs) -> bool:
    """Whether the check raises over the inputs."""
    try:
        _outcome(check, given)
    except Exception:  # the check boundary: any error a check raises
        return True
    return False


def _errored(check: Check, error: Exception, given: _Inputs) -> CheckOutcome:
    """The coverage of a check that raised: naming each file it raises on
    when run over that file alone, or the whole check when it raises on
    none alone, with the error."""
    reason = f"the check failed: {type(error).__name__}: {error}"
    files = sorted({u.path for u in given.model.units if u.kind is UnitKind.FILE})
    named = [p for p in files if _raises(check, given.over(within(given.model, {p})))]
    return CheckOutcome(
        coverage=tuple(Coverage(reason, check=check.name, path=p) for p in named)
        or (Coverage(reason, check=check.name),),
        ran=False,
    )


def run_checks(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
    *,
    radar: Radar | RecordsUnavailable = NO_RADAR,
    checks: Mapping[str, CheckFunction] = TARGET_CHECKS,
) -> Checked:
    """Every implemented check over the model, in catalog order; every
    other check is coverage. The Radar-true checks read the radar. A check
    that raises is caught here, once, and is coverage naming the error."""
    given = _Inputs(model, declaration, records, parameters, radar, checks)
    ran: list[Check] = []
    findings: list[Finding] = []
    coverage: list[Coverage] = []
    for check in CATALOG:
        try:
            outcome = _outcome(check, given)
        except Exception as error:  # the check boundary (Use-case surface)
            outcome = _errored(check, error, given)
        if outcome is None:
            coverage.append(_not_run(check))
            continue
        if outcome.ran:
            ran.append(check)
        findings.extend(outcome.findings)
        coverage.extend(outcome.coverage)
    return Checked(tuple(ran), tuple(findings), tuple(coverage))
