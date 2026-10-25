"""The Injectable quality's checks -- Ports as keywords, No self-wiring, No
reach -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface)."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import Call
from adherence.domain.report import Report
from tests.facts_kit import (
    FS,
    ROOT,
    RULES,
    STORE,
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


def test_measure_with_a_use_case_constructing_an_adapter_finds_it() -> None:
    """Given a use case that constructs a concrete adapter (once itself, once
    in a function nested in it) and also a fake and a domain value, and a
    composition root that constructs the adapter, When No self-wiring runs,
    Then a finding names the use case and the adapter for each construction
    in it, and the fake, the value and the root are clean."""
    files = {USE: b"x\n" * 9, FS: b"x\n" * 9, ROOT: b"x\n" * 9, RULES: b"x\n" * 9}
    definitions = [
        type_(FS, "FsStore", 1),
        type_(FS, "FakeStore", 4),
        type_(RULES, "Order", 1),
        function(USE, "close", 1, end=8),
        function(USE, "close.helper", 6, parent="close", nested=True),
        function(ROOT, "build", 1, end=3),
    ]
    calls = (
        Call(USE, 2, "close", "FsStore"),
        Call(USE, 3, "close", "FakeStore"),
        Call(USE, 4, "close", "Order"),
        Call(USE, 7, "close.helper", "fs.FsStore"),
        Call(ROOT, 2, "build", "FsStore"),
    )

    report = measure_with(files, facts(definitions, calls=calls))

    assert "No self-wiring" in {c.name for c in report.ran}
    found = {
        (f.unit.symbol, f.subject, f.evidence.line)
        for f in _of(report, "No self-wiring")
    }
    assert found == {("close", "FsStore", 2), ("close", "fs.FsStore", 7)}
