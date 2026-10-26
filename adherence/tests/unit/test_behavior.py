"""The Behavior-driven quality's rule checks -- Kept test, Public surface,
Real assertion -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface). Then asserted is judged and stays coverage until
task-064."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import (
    Assertion,
    Body,
    Call,
    CodeModel,
    Definition,
    Layer,
    Target,
    TestCase,
    Unit,
    UnitKind,
)
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    RecordsUnavailable,
    UseCase,
)
from adherence.domain.report import Report
from tests.measure_kit import measure_with

RULES = "src/app/domain/rules.py"
USE = "src/app/application/use.py"
TEST = "tests/test_use.py"


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def test_measure_with_a_test_that_cannot_fail_finds_the_test() -> None:
    """Given a test with no assertion, one whose only assertion is a
    placeholder, one that asserts, one that asserts through pytest.raises,
    and a test-named function outside the test layer, When Real assertion
    runs, Then a finding names each test that cannot fail, and no other."""
    files = {TEST: b"x\n" * 30, RULES: b"x\n" * 5}
    facts = CodeModel(
        test_cases=(
            TestCase(TEST, "test_runs", 1, ("run",), ()),
            TestCase(TEST, "test_placeholder", 5, ("run",), (Assertion("True"),)),
            TestCase(TEST, "test_asserts", 10, ("run",), (Assertion("result == 2"),)),
            TestCase(TEST, "test_raises", 15, ("pytest.raises", "run"), ()),
            TestCase(RULES, "test_helper", 1, (), ()),
        ),
        calls=(
            Call(TEST, 16, "test_raises", "pytest.raises", Target("pytest.raises")),
        ),
    )

    report = measure_with(files, facts)

    assert "Real assertion" in {c.name for c in report.ran}
    found = {(f.unit.symbol, f.evidence.line) for f in _of(report, "Real assertion")}
    assert found == {("test_runs", 1), ("test_placeholder", 5)}
    assert all(f.layer is Layer.TEST for f in _of(report, "Real assertion"))


FS = "src/app/adapters/fs.py"


def _function(path: str, symbol: str, line: int) -> Definition:
    unit = Unit(path, UnitKind.FUNCTION, symbol, line, line + 1, None)
    return Definition(unit, None, Body("return 1", (), ()), (), (), None, False)


def test_measure_with_a_test_past_the_surface_finds_what_it_reached() -> None:
    """Given a test that calls a use case and a public rule, one that reaches
    a private domain helper and an adapter's private method, and calls to a
    private name the repository does not define and to the test file's own
    helper, When Public surface runs, Then a finding names the test and each
    internal it reached, at the call's line."""
    files = {TEST: b"x\n" * 30, RULES: b"x\n" * 10, FS: b"x\n" * 10, USE: b"x\n"}
    definitions = (
        _function(RULES, "price", 1),
        _function(RULES, "_round", 4),
        _function(FS, "FsStore._load", 2),
        _function(USE, "run", 1),
        _function(TEST, "_make", 1),
    )
    calls = (
        ("test_surface", 6, "run"),
        ("test_surface", 7, "rules.price"),
        ("test_reach", 11, "rules._round"),
        ("test_reach", 12, "store._load"),
        ("test_reach", 13, "mock._private"),
        ("test_reach", 14, "_make"),
    )
    facts = CodeModel(
        units=tuple(d.unit for d in definitions),
        definitions=definitions,
        calls=tuple(Call(TEST, line, within, callee) for within, line, callee in calls),
        test_cases=(
            TestCase(
                TEST, "test_surface", 5, ("run", "rules.price"), (Assertion("r"),)
            ),
            TestCase(
                TEST,
                "test_reach",
                10,
                ("rules._round", "store._load", "mock._private", "_make"),
                (Assertion("r"),),
            ),
        ),
    )

    report = measure_with(files, facts)

    assert "Public surface" in {c.name for c in report.ran}
    found = {
        (f.unit.symbol, f.subject, f.evidence.line)
        for f in _of(report, "Public surface")
    }
    assert found == {
        ("test_reach", "test_reach -> rules._round", 11),
        ("test_reach", "test_reach -> store._load", 12),
    }


DESIGN = "docs/design/DESIGN.APP.md"
ARCHITECTURE = "docs/design/ARCHITECTURE.APP.md"
MEASURED = "A repository is measured"
EXPLAINED = "An explanation changes nothing"
PERSISTS = "A report persists"
UNHOMED = "A behavior with no use case"


def test_measure_with_a_behavior_no_test_calls_finds_the_behavior() -> None:
    """Given design behaviors whose use cases a test calls -- one by the
    call's resolved target, one by an unresolved bare name only one function
    carries -- one whose use case only non-test code calls, and one with no
    use case on the surface, When Kept test runs, Then one finding names the
    behavior no test keeps, at its row in the design record."""
    files = {TEST: b"x\n" * 10, USE: b"x\n" * 10}
    definitions = (
        _function(USE, "measure", 1),
        _function(USE, "explain", 4),
        _function(USE, "record_report", 7),
    )
    records = DesignRecords(
        behaviors=(
            Behavior(MEASURED, DESIGN, 10),
            Behavior(EXPLAINED, DESIGN, 11),
            Behavior(PERSISTS, DESIGN, 12),
            Behavior(UNHOMED, DESIGN, 13),
        ),
        surface=(
            UseCase(MEASURED, "measure", ARCHITECTURE, 20),
            UseCase(EXPLAINED, "explain", ARCHITECTURE, 21),
            UseCase(PERSISTS, "record_report", ARCHITECTURE, 22),
        ),
    )
    measure = Target("app.application.use.measure", USE, "measure")
    facts = CodeModel(
        units=tuple(d.unit for d in definitions),
        definitions=definitions,
        calls=(
            Call(USE, 3, "run", "record_report"),
            Call(TEST, 2, "test_measure", "measure", measure),
            Call(TEST, 6, "test_explain", "explain"),
        ),
        test_cases=(
            TestCase(TEST, "test_measure", 1, ("measure",), (Assertion("r"),)),
            TestCase(TEST, "test_explain", 5, ("app.explain",), (Assertion("r"),)),
        ),
    )

    report = measure_with(files, facts, records=records)

    assert "Kept test" in {c.name for c in report.ran}
    (unkept,) = _of(report, "Kept test")
    assert (unkept.unit.path, unkept.unit.symbol) == (DESIGN, PERSISTS)
    assert unkept.unit.kind is UnitKind.BEHAVIOR
    assert unkept.evidence.line == 12 and "record_report" in unkept.subject


def test_measure_without_a_readable_record_covers_kept_test() -> None:
    """Given no readable design record, When Kept test runs, Then it is
    coverage naming the record, never a clean result."""
    report = measure_with(
        {TEST: b"x\n"}, records=RecordsUnavailable(f"{DESIGN} is in draft")
    )

    assert "Kept test" not in {c.name for c in report.ran}
    assert any(c.check == "Kept test" and DESIGN in c.reason for c in report.coverage)
