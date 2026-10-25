"""The Injectable quality's checks -- Ports as keywords, No self-wiring, No
reach -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface)."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.report import Report
from tests.facts_kit import STORE, USE, facts, function, keyword, port, value
from tests.measure_kit import measure_with


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def test_measure_with_a_port_taken_by_position_finds_the_use_case() -> None:
    """Given a use case that takes a port before its values, one that takes
    it after them but by position, one that takes it by name after them,
    and a private application helper taking it by position, When Ports as
    keywords runs, Then a finding names each use case taking a port by
    position, and the port. A port is a named dependency when it is
    keyword-only; the order among keyword-only parameters is not read."""
    files = {USE: b"x\n" * 9, STORE: b"x\n" * 9}
    definitions = [
        *port(STORE, "Store", 1),
        function(USE, "close", 1, (value("store", "Store"), value("order", "Order"))),
        function(USE, "keep", 2, (value("order", "Order"), value("store", "Store"))),
        function(
            USE,
            "fine",
            3,
            (
                value("order", "Order"),
                keyword("store", "Store"),
                keyword("limit", "int"),
            ),
        ),
        function(USE, "_helper", 4, (value("store", "Store"),)),
    ]

    report = measure_with(files, facts(definitions))

    assert "Ports as keywords" in {c.name for c in report.ran}
    found = {(f.unit.symbol, f.subject) for f in _of(report, "Ports as keywords")}
    assert found == {("close", "store: Store"), ("keep", "store: Store")}
    assert all(
        f.check.quality.value == "Injectable" for f in _of(report, "Ports as keywords")
    )
