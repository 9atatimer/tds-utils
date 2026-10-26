"""domain/checks/behavior.py -- every kept test asserts a design behavior
through the public surface.

The rule checks of the Behavior-driven quality: Kept test, Public surface
and Real assertion (DESIGN.ARCH-ADHERENCE.md, The Qualities table:
Behavior-driven), each a pure function over the CodeModel. Then asserted
is a judged question (task-064).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import (
    Assertion,
    Call,
    CodeModel,
    Definition,
    Layer,
    TestCase,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import Behavior, DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

REAL_ASSERTION = catalog_check("Real assertion")
PUBLIC_SURFACE = catalog_check("Public surface")
KEPT_TEST = catalog_check("Kept test")
UNTOLD_HELPERS = "which application function is a use case cannot be told"

# --- Predicates --------------------------------------------------------------


def asserts(call: Call, vocabulary: Vocabulary) -> bool:
    """Whether a call is an assertion API's: it resolves to a name the
    vocabulary lists in full (`pytest.raises`, `unittest.TestCase.assertEqual`),
    or it calls a method the vocabulary lists by its bare name
    (`assert_called_once`, as a mock carries it) on a receiver the analyzer
    cannot resolve. A function or method the measured repository defines
    never asserts, whatever its name."""
    target = call.target
    if target is not None and target.path is not None:
        return False
    if target is not None and target.name in vocabulary.assertion_calls:
        return True
    _receiver, dot, method = call.callee.rpartition(".")
    return bool(dot) and method in vocabulary.assertion_calls


def is_internal(name: str) -> bool:
    """Whether a name is private to its module or type: one leading
    underscore, never a dunder."""
    return name.startswith("_") and not name.startswith("__")


def is_core_or_edge(layer: Layer | None) -> bool:
    """Whether a unit is covered and not a test."""
    return layer is not None and layer is not Layer.TEST


# --- Pure helpers ------------------------------------------------------------


def _definitions(model: CodeModel) -> dict[tuple[str, str], Definition]:
    """Every definition, by its file and symbol."""
    return {(d.unit.path, d.unit.symbol or ""): d for d in model.definitions}


def calls_by_scope(model: CodeModel) -> dict[tuple[str, str | None], list[Call]]:
    """Every call, by the file and the definition it sits in."""
    index: dict[tuple[str, str | None], list[Call]] = {}
    for call in model.calls:
        index.setdefault((call.path, call.within), []).append(call)
    return index


def exercises(calls: Sequence[Call], vocabulary: Vocabulary) -> bool:
    """Whether a test calls something other than an assertion."""
    return any(not asserts(c, vocabulary) for c in calls)


def is_placeholder(
    assertion: Assertion, vocabulary: Vocabulary, *, exercising: bool
) -> bool:
    """Whether an assertion cannot tell a pass from a fail: it asserts a
    literal, or an expression the vocabulary names. A false literal with a
    message, in a test that runs code, is the hand-written failure of an
    unreachable line (`assert False, "should have raised"`): it can fail."""
    if assertion.truth is False and assertion.message and exercising:
        return False
    return (
        assertion.truth is not None
        or assertion.text.strip() in vocabulary.placeholder_assertions
    )


def _placeholders(
    case: TestCase, calls: Sequence[Call], vocabulary: Vocabulary
) -> list[str]:
    exercising = exercises(calls, vocabulary)
    return [
        a.text
        for a in case.assertions
        if is_placeholder(a, vocabulary, exercising=exercising)
    ]


def _tests(model: CodeModel, declaration: Declaration) -> list[tuple[TestCase, Unit]]:
    """Each test case in the test layer, with its unit (the first of its
    file and symbol)."""
    units: dict[tuple[str, str | None], Unit] = {}
    for u in model.units:
        units.setdefault((u.path, u.symbol), u)
    found: list[tuple[TestCase, Unit]] = []
    for case in model.test_cases:
        if layer_of(case.path, case.line, declaration, model.regions) is not Layer.TEST:
            continue
        unit = units.get(
            (case.path, case.symbol),
            Unit(case.path, UnitKind.FUNCTION, case.symbol, case.line, case.line, None),
        )
        found.append((case, unit))
    return found


def _cannot_fail(
    case: TestCase, calls: Sequence[Call], vocabulary: Vocabulary
) -> str | None:
    """Why a test cannot fail, or None when it can."""
    placeholders: Sequence[str] = _placeholders(case, calls, vocabulary)
    if placeholders:
        return f"{case.symbol}: placeholder assertion `{placeholders[0]}`"
    if not case.assertions and not any(asserts(c, vocabulary) for c in calls):
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
    calls = calls_by_scope(model)
    for case, unit in _tests(model, declaration):
        scope = calls.get((case.path, case.symbol), [])
        why = _cannot_fail(case, scope, parameters.vocabulary)
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


def _reaches_internal(
    call: Call, definitions: Mapping[tuple[str, str], Definition]
) -> bool:
    """Whether a call resolves to a private definition of the repository's
    covered non-test code."""
    target = call.target
    if target is None or target.path is None or target.symbol is None:
        return False
    found = definitions.get((target.path, target.symbol))
    return (
        found is not None
        and is_core_or_edge(found.unit.layer)
        and is_internal(target.symbol.rpartition(".")[2])
    )


def _reaches_helper(
    call: Call,
    definitions: Mapping[tuple[str, str], Definition],
    use_cases: frozenset[str],
) -> bool:
    """Whether a call resolves to a function of the application layer that
    is not a use case: the public API is the use-case surface and the pure
    domain beneath it."""
    target = call.target
    if target is None or target.path is None or target.symbol is None:
        return False
    found = definitions.get((target.path, target.symbol))
    return (
        found is not None
        and found.unit.kind is UnitKind.FUNCTION
        and found.unit.layer is Layer.APPLICATION
        and target.symbol not in use_cases
    )


def public_surface(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No test reaches past a use case into a helper or an internal: a test
    call that resolves to a private definition of the repository's covered
    code, or to an application function that is not a use case, is a
    finding, at each such call. Without a readable record the helpers
    cannot be told, and that half is coverage."""
    if not declaration.declared:
        return undeclared(PUBLIC_SURFACE.name)
    definitions = _definitions(model)
    coverage: tuple[Coverage, ...] = ()
    use_cases: frozenset[str] | None = None
    if isinstance(records, RecordsUnavailable):
        reason = f"{UNTOLD_HELPERS}: {records.reason}"
        coverage = (Coverage(reason, check=PUBLIC_SURFACE.name),)
    else:
        use_cases = frozenset(row.function for row in records.surface)
    calls = calls_by_scope(model)
    findings: list[Finding] = []
    for case, unit in _tests(model, declaration):
        for call in calls.get((case.path, case.symbol), ()):
            if not _reaches_internal(call, definitions) and not (
                use_cases is not None and _reaches_helper(call, definitions, use_cases)
            ):
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
    return CheckOutcome(tuple(findings), coverage)


def _unambiguous(model: CodeModel) -> frozenset[str]:
    """The module-level function names exactly one covered non-test
    definition carries."""
    names = Counter(
        d.unit.symbol or ""
        for d in model.definitions
        if d.unit.kind is UnitKind.FUNCTION
        and d.parent is None
        and is_core_or_edge(d.unit.layer)
    )
    return frozenset(n for n, count in names.items() if count == 1)


def _test_helper(
    call: Call, definitions: Mapping[tuple[str, str], Definition]
) -> tuple[str, str] | None:
    """The file and symbol of the test-layer function a call resolves to."""
    target = call.target
    if target is None or target.path is None or target.symbol is None:
        return None
    found = definitions.get((target.path, target.symbol))
    if found is None or found.unit.kind is not UnitKind.FUNCTION:
        return None
    return (target.path, target.symbol) if found.unit.layer is Layer.TEST else None


def _reached(
    case: TestCase,
    calls: Mapping[tuple[str, str | None], Sequence[Call]],
    definitions: Mapping[tuple[str, str], Definition],
) -> list[Call]:
    """Every call a test makes, in its body or in the test-layer helpers it
    calls, transitively; bounded, each helper followed once."""
    start: tuple[str, str] = (case.path, case.symbol)
    seen = {start}
    pending = [start]
    reached: list[Call] = []
    while pending:
        path, symbol = pending.pop()
        for call in calls.get((path, symbol), ()):
            reached.append(call)
            helper = _test_helper(call, definitions)
            if helper is not None and helper not in seen:
                seen.add(helper)
                pending.append(helper)
    return reached


def _kept_name(
    call: Call,
    definitions: Mapping[tuple[str, str], Definition],
    unambiguous: frozenset[str],
) -> str | None:
    """The function of the repository's covered non-test code a call
    reaches: the definition it resolves to, or, when it calls a bare name the
    analyzer could not resolve, the one function of that name. A method of
    some other object by the same name reaches nothing."""
    target = call.target
    if target is None:
        return call.callee if call.callee in unambiguous else None
    if target.path is None or target.symbol is None:
        return None
    found = definitions.get((target.path, target.symbol))
    if found is None or not is_core_or_edge(found.unit.layer):
        return None
    return target.symbol


def _behavior_finding(behavior: Behavior, function: str) -> Finding:
    unit = Unit(
        behavior.path,
        UnitKind.BEHAVIOR,
        behavior.name,
        behavior.line,
        behavior.line,
        None,
    )
    return Finding(
        KEPT_TEST,
        unit,
        None,
        f"{behavior.name}: no test calls {function}",
        Evidence(behavior.path, behavior.line, behavior.name),
    )


def kept_test(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every design behavior has a test that calls its use case, by the
    use-case surface: a call, in the test or a test-layer helper it reaches,
    that resolves to the repository's function of that name. A behavior with
    no use case is Trace's finding, not this check's."""
    if not declaration.declared:
        return undeclared(KEPT_TEST.name)
    if isinstance(records, RecordsUnavailable):
        return CheckOutcome(
            coverage=(Coverage(records.reason, check=KEPT_TEST.name),), ran=False
        )
    calls = calls_by_scope(model)
    definitions = _definitions(model)
    unambiguous = _unambiguous(model)
    kept = {
        name
        for case, _unit in _tests(model, declaration)
        for call in _reached(case, calls, definitions)
        if (name := _kept_name(call, definitions, unambiguous)) is not None
    }
    functions = {row.behavior: row.function for row in records.surface}
    findings = [
        _behavior_finding(behavior, functions[behavior.name])
        for behavior in records.behaviors
        if behavior.name in functions and functions[behavior.name] not in kept
    ]
    return CheckOutcome(tuple(findings))
