"""domain/checks/layered.py -- rules, workflow and wiring are three jobs.

Trace (DESIGN.ARCH-ADHERENCE.md, The Qualities table: Layered), a pure
function over the CodeModel and the design records.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Evidence, Finding, normalised
from adherence.domain.model import (
    CodeModel,
    Definition,
    Layer,
    Signature,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import catalog_check
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    RecordsUnavailable,
    SurfaceRow,
    UseCase,
)

# --- Constants ---------------------------------------------------------------

TRACE = catalog_check("Trace")
# A row's action is its When clause and its observation its Then clause;
# each must hold a word for anything to trace to a function.
WHEN_THEN = re.compile(r"\bWhen\b(?P<when>.*?)\bThen\b(?P<then>.*)", re.DOTALL)
WORD = re.compile(r"\w")
UNTRACEABLE = "the row has no nameable action (When) or observation (Then)"

# A use case's home: its name and its parameter names, in order. The
# keyword-only shape is not compared (architecture Q1 stays open).
Home = tuple[str, tuple[str, ...]]

# --- Predicates --------------------------------------------------------------


def is_use_case_function(definition: Definition) -> bool:
    """Whether a definition can carry a use case: a function at module level
    in the application layer."""
    return (
        definition.unit.kind is UnitKind.FUNCTION
        and definition.unit.layer is Layer.APPLICATION
        and definition.signature is not None
        and definition.parent is None
        and not definition.nested
    )


def is_traceable(scenario: str) -> bool:
    """Whether a behavior row names an action and an observation: a When
    clause and a Then clause after it, each with a word in it."""
    match = WHEN_THEN.search(scenario)
    return (
        match is not None
        and WORD.search(match.group("when")) is not None
        and WORD.search(match.group("then")) is not None
    )


# --- Pure helpers ------------------------------------------------------------


def parameter_names(signature: Signature) -> tuple[str, ...]:
    return tuple(p.name for p in signature.parameters)


def _home_of(name: str, signature: Signature) -> Home:
    return name, parameter_names(signature)


def _shown(home: Home) -> str:
    name, parameters = home
    return f"{name}({', '.join(parameters)})"


def _homes(model: CodeModel) -> dict[Home, list[Definition]]:
    """Every application function that can carry a use case, by its home."""
    homes: dict[Home, list[Definition]] = {}
    for d in model.definitions:
        if is_use_case_function(d) and d.signature is not None:
            name = (d.unit.symbol or "").rpartition(".")[2]
            homes.setdefault(_home_of(name, d.signature), []).append(d)
    return homes


def _homeless(
    behavior: Behavior,
    rows: Mapping[str, SurfaceRow],
    use_cases: Mapping[str, UseCase],
    homes: Mapping[Home, Sequence[Definition]],
) -> str | None:
    """Why a behavior has no home, or None when one application unit
    carries it by the surface's signature. A row nothing could trace is a
    finding against the record."""
    if not is_traceable(behavior.scenario):
        return UNTRACEABLE
    row = rows.get(normalised(behavior.name))
    if row is None:
        return "the use-case surface has no row for it"
    if row.use_case is None:
        return "its use-case surface row names no use case"
    use_case = use_cases.get(row.use_case)
    if use_case is None:
        return f"the use-case surface gives {row.use_case} no signature"
    home = _home_of(use_case.name, use_case.signature)
    found = homes.get(home, ())
    if not found:
        return f"no application unit is {_shown(home)}"
    if len(found) > 1:
        where = ", ".join(sorted(d.unit.path for d in found))
        return f"{len(found)} application units are {_shown(home)}: {where}"
    return None


def _against(behavior: Behavior, why: str) -> Finding:
    """A Trace finding naming the behavior and the record it came from."""
    unit = Unit(
        behavior.path,
        UnitKind.BEHAVIOR,
        behavior.name,
        behavior.line,
        behavior.line,
        None,
    )
    return Finding(
        TRACE,
        unit,
        None,
        f"{behavior.name}: {why}",
        Evidence(behavior.path, behavior.line, behavior.name),
    )


def trace(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every design behavior resolves to one application unit, by the
    use-case surface's signature."""
    if not declaration.declared:
        return undeclared(TRACE.name)
    if isinstance(records, RecordsUnavailable):
        return CheckOutcome(
            coverage=(Coverage(records.reason, check=TRACE.name),), ran=False
        )
    rows = {normalised(r.behavior): r for r in records.surface}
    use_cases = {u.name: u for u in records.use_cases}
    homes = _homes(model)
    findings = [
        _against(behavior, why)
        for behavior in records.behaviors
        if (why := _homeless(behavior, rows, use_cases, homes)) is not None
    ]
    return CheckOutcome(tuple(findings))
