"""domain/checks/behavior.py -- every kept test asserts a design behavior
through the public surface.

The rule checks of the Behavior-driven quality: Kept test, Public surface
and Real assertion (DESIGN.ARCH-ADHERENCE.md, The Qualities table:
Behavior-driven), each a pure function over the CodeModel. Then asserted
is a judged question (task-064).
"""

from __future__ import annotations

from collections.abc import Sequence

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import CodeModel, Layer, TestCase, Unit, UnitKind
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

REAL_ASSERTION = catalog_check("Real assertion")
PUBLIC_SURFACE = catalog_check("Public surface")

# --- Predicates --------------------------------------------------------------


def is_named(callee: str, names: frozenset[str]) -> bool:
    """Whether a callee, by its full dotted name or its last part, is named."""
    return callee in names or callee.rpartition(".")[2] in names


def asserts_by_call(case: TestCase, vocabulary: Vocabulary) -> bool:
    """Whether a test calls something that asserts, as `pytest.raises` does."""
    return any(is_named(c, vocabulary.assertion_calls) for c in case.calls)


def is_internal(name: str) -> bool:
    """Whether a name is private to its module or type: one leading
    underscore, never a dunder."""
    return name.startswith("_") and not name.startswith("__")


# --- Pure helpers ------------------------------------------------------------


def _placeholders(case: TestCase, vocabulary: Vocabulary) -> list[str]:
    return [
        a for a in case.assertions if a.strip() in vocabulary.placeholder_assertions
    ]


def _tests(model: CodeModel, declaration: Declaration) -> list[tuple[TestCase, Unit]]:
    """Each test case in the test layer, with its unit."""
    found: list[tuple[TestCase, Unit]] = []
    for case in model.test_cases:
        if layer_of(case.path, case.line, declaration, model.regions) is not Layer.TEST:
            continue
        unit = next(
            (u for u in model.units if u.path == case.path and u.symbol == case.symbol),
            Unit(case.path, UnitKind.FUNCTION, case.symbol, case.line, case.line, None),
        )
        found.append((case, unit))
    return found


def _cannot_fail(case: TestCase, vocabulary: Vocabulary) -> str | None:
    """Why a test cannot fail, or None when it can."""
    placeholders: Sequence[str] = _placeholders(case, vocabulary)
    if placeholders:
        return f"{case.symbol}: placeholder assertion `{placeholders[0]}`"
    if not case.assertions and not asserts_by_call(case, vocabulary):
        return f"{case.symbol}: no assertion"
    return None


def real_assertion(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No test without an assertion and no placeholder assertion."""
    if not declaration.declared:
        return undeclared(REAL_ASSERTION.name)
    findings: list[Finding] = []
    for case, unit in _tests(model, declaration):
        why = _cannot_fail(case, parameters.vocabulary)
        if why is not None:
            findings.append(
                Finding(
                    REAL_ASSERTION,
                    unit,
                    Layer.TEST,
                    why,
                    Evidence(case.path, case.line, case.symbol),
                )
            )
    return CheckOutcome(tuple(findings))


def _internals(model: CodeModel) -> frozenset[str]:
    """The private names the covered non-test definitions carry."""
    return frozenset(
        name
        for d in model.definitions
        if d.unit.layer is not None and d.unit.layer is not Layer.TEST
        if is_internal(name := (d.unit.symbol or "").rpartition(".")[2])
    )


def public_surface(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No test reaches past a use case into a helper or an internal: a test
    that calls a private definition of the repository's covered code is a
    finding, at each such call."""
    if not declaration.declared:
        return undeclared(PUBLIC_SURFACE.name)
    internals = _internals(model)
    findings: list[Finding] = []
    for case, unit in _tests(model, declaration):
        for call in model.calls:
            reached = call.callee.rpartition(".")[2]
            if call.path != case.path or call.within != case.symbol:
                continue
            if reached not in internals:
                continue
            findings.append(
                Finding(
                    PUBLIC_SURFACE,
                    unit,
                    Layer.TEST,
                    f"{case.symbol} -> {call.callee}",
                    Evidence(call.path, call.line, call.callee),
                )
            )
    return CheckOutcome(tuple(findings))
