"""The Layered quality's rule checks -- Trace, Purity's rule part, Wiring,
Anatomy -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface)."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import (
    Body,
    CodeModel,
    Definition,
    Parameter,
    Signature,
    Unit,
    UnitKind,
)
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    SurfaceRow,
    UseCase,
)
from adherence.domain.report import Report
from tests.measure_kit import measure_with

DESIGN = "docs/design/DESIGN.TOOL.md"
ARCHITECTURE = "docs/design/ARCHITECTURE.TOOL.md"
USE = "src/app/application/use.py"
RULES = "src/app/domain/rules.py"
CLOSED = "An order is closed"
SCENARIO = "Given an open order, When it is closed, Then the store holds it closed"


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def _parameters(names: str, keyword_only: str = "") -> tuple[Parameter, ...]:
    return tuple(
        Parameter(name, None, name in keyword_only.split(), False)
        for name in names.split()
    )


def _function(
    path: str, symbol: str, parameters: tuple[Parameter, ...], line: int = 1
) -> Definition:
    unit = Unit(path, UnitKind.FUNCTION, symbol, line, line + 1, None)
    return Definition(
        unit=unit,
        signature=Signature(parameters, None),
        body=Body("return x", (), ()),
        bases=(),
        decorators=(),
        parent=None,
        nested=False,
    )


def _carried(
    behavior: str, use_case: str, names: str, keyword_only: str = ""
) -> DesignRecords:
    """Records stating one behavior, its surface row naming the use case,
    and the use case's signature."""
    return DesignRecords(
        behaviors=(Behavior(behavior, SCENARIO, DESIGN, 9),),
        use_cases=(
            UseCase(
                use_case,
                Signature(_parameters(names, keyword_only), "str"),
                ARCHITECTURE,
                12,
            ),
        ),
        surface=(SurfaceRow(behavior, use_case, ARCHITECTURE, 12),),
    )


def test_measure_behavior_carried_by_its_use_case_passes_trace() -> None:
    """Given a design behavior carried by one application function with the
    surface's name and parameter names, When Trace runs, Then Trace ran and
    there is no Trace finding. The match is name plus parameter names; the
    keyword-only shape is not compared (architecture Q1 stays open), so a
    port the surface takes by keyword and the code by position still homes."""
    records = _carried(CLOSED, "close_order", "order store", keyword_only="store")
    facts = CodeModel(
        definitions=(_function(USE, "close_order", _parameters("order store")),)
    )

    report = measure_with(
        {USE: b"def close_order(order, store): ...\n"}, facts, records=records
    )

    assert "Trace" in [c.name for c in report.ran]
    assert _of(report, "Trace") == []


def _merged(*records: DesignRecords) -> DesignRecords:
    return DesignRecords(
        behaviors=tuple(b for r in records for b in r.behaviors),
        use_cases=tuple(u for r in records for u in r.use_cases),
        surface=tuple(s for r in records for s in r.surface),
    )


def test_measure_behavior_no_application_unit_carries_is_found() -> None:
    """Given design behaviors whose use case no function carries, one whose
    namesake takes other parameters, one carried only by a domain function,
    one carried by two application functions, and one with no surface row,
    When Trace runs, Then a finding names each behavior and the record it
    came from."""
    missing = _carried("An order is missing", "find_order", "order_id")
    renamed = _carried("An order is renamed", "rename_order", "order name")
    ruled = _carried("An order is ruled", "rule_order", "order")
    twice = _carried("An order is doubled", "double_order", "order")
    unsurfaced = DesignRecords(
        behaviors=(Behavior("An order is lost", SCENARIO, DESIGN, 14),)
    )
    other = "src/app/application/other.py"
    facts = CodeModel(
        definitions=(
            _function(USE, "rename_order", _parameters("order title")),
            _function(RULES, "rule_order", _parameters("order")),
            _function(USE, "double_order", _parameters("order"), line=5),
            _function(other, "double_order", _parameters("order")),
        )
    )
    files = {USE: b"x = 1\n", RULES: b"x = 1\n", other: b"x = 1\n"}

    report = measure_with(
        files,
        facts,
        records=_merged(missing, renamed, ruled, twice, unsurfaced),
    )

    homeless = _of(report, "Trace")
    assert sorted(f.unit.symbol or "" for f in homeless) == [
        "An order is doubled",
        "An order is lost",
        "An order is missing",
        "An order is renamed",
        "An order is ruled",
    ]
    for finding in homeless:
        assert (finding.unit.path, finding.evidence.path) == (DESIGN, DESIGN)
        assert finding.unit.kind.value == "design behavior"
        assert finding.unit.symbol in finding.subject
        assert finding.check.quality.value == "Layered"
    lost = next(f for f in homeless if f.unit.symbol == "An order is lost")
    assert lost.evidence.line == 14
