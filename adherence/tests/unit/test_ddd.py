"""The Domain-driven quality's rule parts -- Language, Boundary, Anemic --
driven through `measure` with a fake behind every port (DESIGN.ARCH-
ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Use-case
surface). The judged parts are task-064's."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import Layer, Write
from adherence.domain.records import DesignRecords, Term
from adherence.domain.report import Report
from tests.facts_kit import (
    FS,
    RULES,
    USE,
    facts,
    field,
    function,
    keyword,
    method,
    type_,
    value,
)
from tests.measure_kit import measure_with


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def test_measure_with_a_field_written_outside_its_type_finds_the_write() -> None:
    """Given a domain value type, a use case and a domain function that each
    write one of its fields through a parameter of that type, and writes
    the check cannot pin on it (its own method, a parameter with no
    annotation, an attribute it does not declare, an adapter's own field),
    When Boundary runs, Then a finding names the type, the writer and the
    owning unit for each foreign write, and the rest are clean."""
    files = {RULES: b"x\n" * 12, USE: b"x\n" * 9, FS: b"x\n" * 9}
    definitions = [
        type_(RULES, "Order", 1, end=4),
        function(RULES, "Order.close", 3, (value("self"),), parent="Order", end=4),
        function(RULES, "reopen", 6, (value("order", '"Order | None"'),), end=7),
        function(USE, "close", 1, (value("order", "Order"),), end=4),
        function(USE, "touch", 6, (value("order"),), end=8),
        type_(FS, "FsStore", 1, end=4),
        function(FS, "FsStore.__init__", 2, (value("self"),), parent="FsStore", end=3),
    ]
    members = (
        field(RULES, "Order", "total", 2),
        field(RULES, "Order", "status", 2),
        method(RULES, "Order", "close", 3),
        field(FS, "FsStore", "root", 3),
    )
    writes = (
        Write(RULES, 4, "Order.close", "self", "status"),
        Write(RULES, 7, "reopen", "order", "status"),
        Write(USE, 2, "close", "order", "status"),
        Write(USE, 3, "close", "order", "memo"),
        Write(USE, 7, "touch", "order", "status"),
        Write(FS, 3, "FsStore.__init__", "self", "root"),
    )

    report = measure_with(files, facts(definitions, members=members, writes=writes))

    assert "Boundary" in {c.name for c in report.ran}
    found = {
        (f.unit.symbol, f.layer, f.subject, f.evidence.line)
        for f in _of(report, "Boundary")
    }
    assert found == {
        (
            "reopen",
            Layer.DOMAIN,
            f"Order.status written by reopen; owned by Order in {RULES}",
            7,
        ),
        (
            "close",
            Layer.APPLICATION,
            f"Order.status written by close; owned by Order in {RULES}",
            2,
        ),
    }
    assert all(
        f.check.quality.value == "Domain-driven" for f in _of(report, "Boundary")
    )
    assert any(
        c.check == "Boundary" and "invariant_broken" in c.reason
        for c in report.coverage
    ), "the judged part is coverage, never a silent pass"


DESIGN = "docs/design/DESIGN.APP.md"
LANGUAGE = DesignRecords(
    domain_language=(
        Term("Order", DESIGN, 40),
        Term("Use case", DESIGN, 41),
        Term("Known flaws", DESIGN, 42),
    )
)


def test_measure_with_a_noun_the_domain_language_lacks_finds_it() -> None:
    """Given use cases whose signatures name types the Domain Language
    defines (under its spelling, in CamelCase, or plural), types it does not
    define, and the language's own types, and a private application helper
    and a domain function naming undefined types, When Language runs, Then
    a finding names each undefined noun and the use case's signature, and
    the rest are clean. The nouns read are the type names a signature
    carries; parameter names are not read as nouns."""
    files = {USE: b"x\n" * 9, RULES: b"x\n" * 9}
    definitions = [
        function(
            USE,
            "close",
            1,
            (value("order", "Order"), keyword("store", "OrderStore")),
            returns="Receipt",
        ),
        function(USE, "flaws", 2, (value("case", "UseCase"),), returns="KnownFlaws"),
        function(
            USE,
            "every",
            3,
            (keyword("orders", "Sequence[Order]"),),
            returns="tuple[Orders, ...] | None",
        ),
        function(USE, "_parse", 4, (value("raw", "Blob"),)),
        function(RULES, "price", 1, (value("item", "Gadget"),)),
    ]

    report = measure_with(files, facts(definitions), records=LANGUAGE)

    assert "Language" in {c.name for c in report.ran}
    found = {(f.unit.symbol, f.subject) for f in _of(report, "Language")}
    assert found == {
        ("close", "OrderStore in close"),
        ("close", "Receipt in close"),
    }
    assert all(f.layer is Layer.APPLICATION for f in _of(report, "Language"))
    assert any(
        c.check == "Language" and "same_concept" in c.reason for c in report.coverage
    ), "the judged part is coverage, never a silent pass"
