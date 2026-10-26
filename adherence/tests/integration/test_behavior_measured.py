"""The Behavior-driven quality's rule checks over real Python sources: the
Python analyzer models them and `measure` runs with the shipped
vocabulary, every other port a fake (DESIGN.ARCH-ADHERENCE.md, Behaviors:
A test that cannot fail is found, A test past the surface is found, A
behavior with no kept test is found)."""

from __future__ import annotations

from adherence.adapters.python_ast import PythonCodeModel
from adherence.container import SHIPPED_VOCABULARY
from adherence.domain.finding import Finding
from adherence.domain.model import CodeLanguage
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import Report
from tests.measure_kit import measure_with

TEST = "tests/test_use.py"


def _measured(
    files: dict[str, bytes], records: DesignRecords | RecordsUnavailable | None = None
) -> Report:
    return measure_with(
        files,
        analyzers={CodeLanguage.PYTHON: PythonCodeModel()},
        records=records,
        vocabulary=SHIPPED_VOCABULARY,
    )


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def _cannot_fail(report: Report) -> set[str]:
    assert "Real assertion" in {c.name for c in report.ran}
    return {f.unit.symbol or "" for f in _of(report, "Real assertion")}


def test_an_assertion_of_any_literal_is_a_placeholder() -> None:
    """Given tests whose only assertion is a literal -- a number, a string,
    a tuple, a negative number -- and one that asserts a result, When Real
    assertion runs, Then each literal-only test is found and the real one is
    not (Self-review R3)."""
    source = (
        b"def test_two():\n"
        b"    run()\n"
        b"    assert 2\n"
        b"def test_ok():\n"
        b'    assert "ok"\n'
        b"def test_tuple():\n"
        b"    assert (1, 2)\n"
        b"def test_negative():\n"
        b"    assert -1\n"
        b"def test_real():\n"
        b"    assert run() == 1\n"
    )

    report = _measured({TEST: source})

    assert _cannot_fail(report) == {
        "test_two",
        "test_ok",
        "test_tuple",
        "test_negative",
    }
