"""The Complete quality's rule checks -- Stub, Complexity, Duplication --
driven through `measure` with a fake behind every port (DESIGN.ARCH-
ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface).
Done and Hand-rolled are judged and stay coverage until task-064."""

from __future__ import annotations

from adherence.adapters.fakes import FakeComplexity, FakeDuplication
from adherence.domain.finding import Finding
from adherence.domain.model import (
    Body,
    Clone,
    CodeModel,
    Complexity,
    Definition,
    Layer,
    MetricsUnavailable,
    Span,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Limits
from adherence.domain.report import Report
from tests.measure_kit import measure_with

RULES = "src/app/domain/rules.py"
USE = "src/app/application/use.py"
STORE = "src/app/ports/store.py"
FS = "src/app/adapters/fs.py"
TEST = "tests/test_use.py"


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def _function(
    path: str,
    symbol: str,
    line: int,
    *,
    stub: str | None = None,
    sleeps: tuple[int, ...] = (),
    decorators: tuple[str, ...] = (),
    parent: str | None = None,
) -> Definition:
    unit = Unit(path, UnitKind.FUNCTION, symbol, line, line + 2, None)
    body = Body(stub or "return 1", (stub,) if stub else (), sleeps)
    return Definition(unit, None, body, (), decorators, parent, False)


def _type(path: str, symbol: str, line: int, bases: tuple[str, ...]) -> Definition:
    unit = Unit(path, UnitKind.TYPE, symbol, line, line + 5, None)
    return Definition(unit, None, Body("", (), ()), bases, (), None, False)


def test_measure_with_a_stubbed_function_finds_the_stub() -> None:
    """Given a domain function whose body is `pass`, an application function
    that sleeps in place of its work, a port's declared method, an abstract
    method, a test's placeholder and a function that works, When Stub runs,
    Then a finding names each stubbed non-test function, and nothing else."""
    files = {path: b"x\n" * 12 for path in (RULES, USE, STORE, FS, TEST)}
    definitions = (
        _function(RULES, "load", 1, stub="pass"),
        _function(RULES, "price", 5),
        _function(USE, "run", 1, sleeps=(2,)),
        _type(STORE, "Store", 1, ("Protocol",)),
        _function(STORE, "Store.save", 2, stub="...", parent="Store"),
        _type(FS, "Base", 1, ("ABC",)),
        _function(
            FS,
            "Base.open",
            2,
            stub="...",
            decorators=("abc.abstractmethod",),
            parent="Base",
        ),
        _function(TEST, "helper", 1, stub="pass"),
    )
    facts = CodeModel(units=tuple(d.unit for d in definitions), definitions=definitions)

    report = measure_with(files, facts)

    assert "Stub" in {c.name for c in report.ran}
    found = {(f.unit.path, f.unit.symbol, f.evidence.line) for f in _of(report, "Stub")}
    assert found == {(RULES, "load", 1), (USE, "run", 2)}
    assert {f.layer for f in _of(report, "Stub")} == {
        Layer.DOMAIN,
        Layer.APPLICATION,
    }


def test_measure_with_a_function_over_the_ceiling_finds_its_complexity() -> None:
    """Given functions whose complexity is under, at and over the complexity
    ceiling, and one over it in a file no layer covers, When Complexity runs,
    Then one finding names the covered function over the ceiling, and the
    ceiling."""
    scratch = "scratch.py"
    files = {RULES: b"x\n" * 12, USE: b"x\n" * 12, scratch: b"x\n" * 12}
    units = (
        Unit(RULES, UnitKind.FUNCTION, "price", 3, 9, None),
        Unit(USE, UnitKind.FUNCTION, "run", 1, 9, None),
    )
    complexity = FakeComplexity(
        (
            Complexity(RULES, "price", 3, 12),
            Complexity(USE, "run", 1, 10),
            Complexity(RULES, "small", 10, 2),
            Complexity(scratch, "tangle", 1, 50),
        )
    )

    report = measure_with(
        files,
        CodeModel(units=units),
        complexity=complexity,
        limits=Limits(evidence_bound=200, complexity_ceiling=10),
    )

    (over,) = _of(report, "Complexity")
    assert (over.unit.path, over.unit.symbol, over.evidence.line) == (RULES, "price", 3)
    assert "12" in over.subject and "10" in over.subject
    assert over.layer is Layer.DOMAIN


def test_measure_with_no_complexity_ceiling_covers_complexity() -> None:
    """Given no complexity ceiling supplied, When Complexity runs, Then it is
    coverage naming the missing ceiling, never a clean result."""
    report = measure_with(
        {RULES: b"x\n"}, complexity=FakeComplexity((Complexity(RULES, "f", 1, 99),))
    )

    assert "Complexity" not in {c.name for c in report.ran}
    assert any(
        c.check == "Complexity" and "ceiling" in c.reason for c in report.coverage
    )


def test_measure_with_a_clone_over_the_ceiling_finds_both_stretches() -> None:
    """Given a clone longer than the duplication ceiling across two covered
    files, one at the ceiling, and one reaching a file no layer covers, When
    Duplication runs, Then one finding names both stretches of the clone over
    the ceiling."""
    scratch = "scratch.py"
    files = {RULES: b"x\n" * 40, USE: b"x\n" * 40, scratch: b"x\n" * 40}
    duplication = FakeDuplication(
        (
            Clone(Span(RULES, 3, 16), Span(USE, 20, 33), 14),
            Clone(Span(RULES, 20, 29), Span(USE, 1, 10), 10),
            Clone(Span(USE, 1, 20), Span(scratch, 1, 20), 20),
        )
    )

    report = measure_with(
        files,
        duplication=duplication,
        limits=Limits(evidence_bound=200, duplication_ceiling=10),
    )

    (clone,) = _of(report, "Duplication")
    assert (clone.unit.path, clone.evidence.line) == (RULES, 3)
    assert f"{RULES}:3-16" in clone.subject and f"{USE}:20-33" in clone.subject
    assert clone.layer is Layer.DOMAIN


def test_measure_with_no_duplication_ceiling_covers_duplication() -> None:
    """Given no duplication ceiling supplied, When Duplication runs, Then it
    is coverage naming the missing ceiling, never a clean result."""
    clones = (Clone(Span(RULES, 1, 50), Span(USE, 1, 50), 50),)

    report = measure_with({RULES: b"x\n"}, duplication=FakeDuplication(clones))

    assert "Duplication" not in {c.name for c in report.ran}
    assert any(
        c.check == "Duplication" and "ceiling" in c.reason for c in report.coverage
    )


def test_measure_with_the_complexity_tool_unavailable_covers_it() -> None:
    """Given complexity tooling that is not installed, When a run is asked
    for, Then Complexity is coverage naming why, never a clean result."""
    report = measure_with(
        {RULES: b"x\n"},
        complexity=FakeComplexity(MetricsUnavailable("lizard is not installed")),
        limits=Limits(evidence_bound=200, complexity_ceiling=10),
    )

    assert "Complexity" not in {c.name for c in report.ran}
    assert any(
        c.check == "Complexity" and "lizard is not installed" in c.reason
        for c in report.coverage
    )


def test_measure_names_a_method_over_the_ceiling_by_its_qualified_symbol() -> None:
    """Given complexity tooling that names a method without its type, as
    lizard does for Python, When Complexity finds it, Then the finding names
    the analyzer's unit for that method, its type included."""
    files = {RULES: b"x\n" * 12}
    units = (Unit(RULES, UnitKind.FUNCTION, "Order.total", 4, 9, None),)

    report = measure_with(
        files,
        CodeModel(units=units),
        complexity=FakeComplexity((Complexity(RULES, "total", 4, 20),)),
        limits=Limits(evidence_bound=200, complexity_ceiling=10),
    )

    (over,) = _of(report, "Complexity")
    assert over.unit.symbol == "Order.total"


def test_measure_reads_a_generic_protocol_as_abstract() -> None:
    """Given two adapter-layer generic protocols, by bare and dotted name,
    whose methods are `...`, When Stub runs, Then neither method is a stub:
    the subscript does not hide the abstract base (Self-review R12)."""
    files = {FS: b"x\n" * 12}
    definitions = (
        _type(FS, "Source", 1, ("Protocol[T]",)),
        _function(FS, "Source.read", 2, stub="...", parent="Source"),
        _type(FS, "Sink", 5, ("typing.Protocol[T, U]",)),
        _function(FS, "Sink.write", 6, stub="...", parent="Sink"),
    )
    facts = CodeModel(units=tuple(d.unit for d in definitions), definitions=definitions)

    report = measure_with(files, facts)

    assert "Stub" in {c.name for c in report.ran}
    assert _of(report, "Stub") == []
