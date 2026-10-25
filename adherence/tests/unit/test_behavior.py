"""The Behavior-driven quality's rule checks -- Kept test, Public surface,
Real assertion -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface). Then asserted is judged and stays coverage until
task-064."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import CodeModel, Layer, TestCase
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
