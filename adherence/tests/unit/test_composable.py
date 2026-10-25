"""The Composable quality's checks -- Values in and out, No nesting, Helpers
take values -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface)."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import Layer
from adherence.domain.report import Report
from tests.facts_kit import (
    RULES,
    STORE,
    TEST,
    USE,
    facts,
    function,
    keyword,
    port,
    type_,
    value,
)
from tests.measure_kit import measure_with


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def test_measure_with_a_function_inside_another_finds_both() -> None:
    """Given a function defined inside a use case, a method of a class
    defined inside a domain function, and a function nested in a test, When
    No nesting runs, Then a finding names each non-test nested function and
    the function enclosing it, and the test's is clean."""
    files = {USE: b"x\n" * 9, RULES: b"x\n" * 9, TEST: b"x\n" * 9}
    definitions = [
        function(USE, "close_order", 1, end=6),
        function(USE, "close_order.helper", 3, parent="close_order", nested=True),
        function(RULES, "make", 1, end=8),
        type_(RULES, "make.Local", 2, parent="make", nested=True),
        function(RULES, "make.Local.run", 3, parent="make.Local", nested=True),
        function(TEST, "test_it", 1, end=5),
        function(TEST, "test_it.inner", 2, parent="test_it", nested=True),
    ]

    report = measure_with(files, facts(definitions))

    assert "No nesting" in {c.name for c in report.ran}
    found = {(f.unit.symbol, f.subject, f.layer) for f in _of(report, "No nesting")}
    assert found == {
        (
            "close_order.helper",
            "close_order.helper inside close_order",
            Layer.APPLICATION,
        ),
        ("make.Local.run", "make.Local.run inside make", Layer.DOMAIN),
    }
    assert all(f.check.quality.value == "Composable" for f in _of(report, "No nesting"))


def test_measure_with_a_helper_taking_a_port_or_callable_finds_both() -> None:
    """Given domain helpers that take a port, a callable and (as a method) a
    port, a domain helper that takes values, and a use case that takes the
    port, When Helpers take values runs, Then a finding names each helper
    and the parameter, and the helper taking values and the use case are
    clean."""
    files = {RULES: b"x\n" * 9, USE: b"x\n" * 9, STORE: b"x\n" * 9}
    definitions = [
        *port(STORE, "Store", 1),
        type_(RULES, "Order", 1, end=3),
        function(
            RULES,
            "Order.keep",
            2,
            (value("self"), value("store", '"Store"')),
            parent="Order",
        ),
        function(
            RULES, "price", 5, (value("order", "Order"), keyword("store", "Store"))
        ),
        function(RULES, "apply", 6, (value("rule", "Callable[[int], int]"),)),
        function(RULES, "total", 7, (value("order", "Order"),), returns="int"),
        function(USE, "close", 1, (value("order", "Order"), keyword("store", "Store"))),
    ]

    report = measure_with(files, facts(definitions))

    assert "Helpers take values" in {c.name for c in report.ran}
    found = {(f.unit.symbol, f.subject) for f in _of(report, "Helpers take values")}
    assert found == {
        ("Order.keep", 'store: "Store"'),
        ("price", "store: Store"),
        ("apply", "rule: Callable[[int], int]"),
    }
