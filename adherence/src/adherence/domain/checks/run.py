"""domain/checks/run.py -- every target-level check over one CodeModel.

The checks implemented so far, by catalog name; measure calls run_checks
once per target.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
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
from adherence.domain.model import (
    CodeLanguage,
    CodeModel,
    UnitKind,
    language_of,
    within,
    without,
)
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG, Check, CheckKind, Quality
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable
from adherence.domain.report import FinishedCheck

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


def reads_language(check: Check, language: str | None) -> bool:
    """Whether the check reads a language (None: a file in none)."""
    if language is None or language not in READ_BY:
        return True
    return check.name in READ_BY[language]


def reads(check: Check, path: str) -> bool:
    """Whether the check reads the language a file is written in."""
    return reads_language(check, language_of(path))


def unread_by(check: Check, model: CodeModel) -> tuple[str, ...]:
    """Every file whose language the check does not read: the language its
    unit was measured in, else the one its extension names."""
    return tuple(
        u.path
        for u in model.units
        if u.kind is UnitKind.FILE
        and not reads_language(check, u.language or language_of(u.path))
    )


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


def each_check(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
    *,
    radar: Radar | RecordsUnavailable = NO_RADAR,
    checks: Mapping[str, CheckFunction] = TARGET_CHECKS,
) -> Iterator[FinishedCheck]:
    """Every check over the model, in catalog order, each as it finishes: an
    implemented one by its outcome, any other as coverage. The Radar-true
    checks read the radar. A check that raises is caught here, once, and is
    coverage naming the error."""
    given = _Inputs(model, declaration, records, parameters, radar, checks)
    # A file in no layer is already coverage (domain/coverage, UNASSIGNED).
    layered = {u.path for u in model.units if u.layer is not None}
    languages = {
        u.path: u.language or language_of(u.path)
        for u in model.units
        if u.kind is UnitKind.FILE
    }
    for check in CATALOG:
        unread = unread_by(check, model)
        scoped = given.over(without(model, unread))
        try:
            outcome = _outcome(check, scoped)
        except Exception as error:  # the check boundary (Use-case surface)
            outcome = _errored(check, error, scoped)
        if outcome is None:
            yield FinishedCheck(check, coverage=(_not_run(check),), ran=False)
            continue
        skipped = tuple(
            Coverage(f"does not read {languages[path]}", check=check.name, path=path)
            for path in unread
            if path in layered and outcome.ran
        )
        yield FinishedCheck(
            check, outcome.findings, (*skipped, *outcome.coverage), ran=outcome.ran
        )


def gathered(finished: Iterator[FinishedCheck] | tuple[FinishedCheck, ...]) -> Checked:
    """What the finished checks did, together."""
    done = tuple(finished)
    return Checked(
        ran=tuple(f.check for f in done if f.ran),
        findings=tuple(finding for f in done for finding in f.findings),
        coverage=tuple(c for f in done for c in f.coverage),
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
    other check is coverage (each_check, gathered)."""
    return gathered(
        each_check(model, declaration, records, parameters, radar=radar, checks=checks)
    )
