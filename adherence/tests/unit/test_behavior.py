"""The Behavior-driven quality's rule checks -- Kept test, Public surface,
Real assertion -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface). Then asserted is judged and stays coverage until
task-064."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import (
    Body,
    Call,
    CodeModel,
    Definition,
    Layer,
    TestCase,
    Unit,
    UnitKind,
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
            TestCase(TEST, "test_placeholder", 5, ("run",), ("True",)),
            TestCase(TEST, "test_asserts", 10, ("run",), ("result == 2",)),
            TestCase(TEST, "test_raises", 15, ("pytest.raises", "run"), ()),
            TestCase(RULES, "test_helper", 1, (), ()),
        )
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
            TestCase(TEST, "test_surface", 5, ("run", "rules.price"), ("r",)),
            TestCase(
                TEST,
                "test_reach",
                10,
                ("rules._round", "store._load", "mock._private", "_make"),
                ("r",),
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
