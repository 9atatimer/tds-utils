"""The Complete quality's rule checks -- Stub, Complexity, Duplication --
driven through `measure` with a fake behind every port (DESIGN.ARCH-
ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface).
Done and Hand-rolled are judged and stay coverage until task-064."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import (
    Body,
    CodeModel,
    Definition,
    Layer,
    Unit,
    UnitKind,
)
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
