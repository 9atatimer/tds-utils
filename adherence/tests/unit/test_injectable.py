"""The Injectable quality's checks -- Ports as keywords, No self-wiring, No
reach -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface)."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import (
    Access,
    AccessKind,
    Binding,
    Call,
    Reference,
    ReferenceKind,
)
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
    keyword-only and a value comes before it."""
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
    in a function nested in it) and also a domain value, and a composition
    root that constructs the adapter, When No self-wiring runs, Then a
    finding names the use case and the adapter for each construction in it,
    and the value and the root are clean."""
    files = {
        USE: b"x\n" * 9,
        FS: b"x\n" * 9,
        ROOT: b"x\n" * 9,
        RULES: b"x\n" * 9,
        STORE: b"x\n" * 9,
    }
    definitions = [
        *port(STORE, "Store", 1),
        type_(FS, "FsStore", 1, bases=("Store",)),
        type_(RULES, "Order", 1),
        function(USE, "close", 1, end=8),
        function(USE, "close.helper", 6, parent="close", nested=True),
        function(ROOT, "build", 1, end=3),
    ]
    calls = (
        Call(USE, 2, "close", "FsStore"),
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


def test_measure_with_a_core_unit_reading_a_global_finds_the_reach() -> None:
    """Given a domain function and a domain module reading the environment, a
    use case declaring a global, and a use case reading a singleton, and an
    adapter and a composition root reading the environment, When No reach
    runs, Then a finding names each core unit and what it reached, and the
    adapter and the root are clean."""
    files = {RULES: b"x\n" * 9, USE: b"x\n" * 9, FS: b"x\n" * 9, ROOT: b"x\n" * 9}
    definitions = [
        function(RULES, "price", 2, end=4),
        function(USE, "close", 1, end=3),
        function(USE, "run", 5, end=7),
        function(FS, "save", 1, end=3),
        function(ROOT, "build", 1, end=3),
    ]
    accesses = (
        Access(RULES, 3, "price", AccessKind.ENVIRONMENT, "os.environ"),
        Access(RULES, 8, None, AccessKind.ENVIRONMENT, "os.getenv"),
        Access(USE, 2, "close", AccessKind.GLOBAL, "COUNTER"),
        Access(FS, 2, "save", AccessKind.ENVIRONMENT, "os.environ"),
        Access(ROOT, 2, "build", AccessKind.ENVIRONMENT, "os.environ"),
    )
    references = (
        Reference(USE, 6, "run", ReferenceKind.NAME, "sys.argv"),
        Reference(USE, 6, "run", ReferenceKind.NAME, "sys.version_info"),
    )

    report = measure_with(
        files, facts(definitions, accesses=accesses, references=references)
    )

    assert "No reach" in {c.name for c in report.ran}
    found = {(f.unit.path, f.unit.symbol, f.subject) for f in _of(report, "No reach")}
    assert found == {
        (RULES, "price", "the environment: os.environ"),
        (RULES, None, "the environment: os.getenv"),
        (USE, "close", "a global: COUNTER"),
        (USE, "run", "a singleton: sys.argv"),
    }


def test_measure_with_a_keyword_port_before_its_values_finds_the_use_case() -> None:
    """Given a use case taking every parameter by keyword, its port before
    its value, one taking a value by position and then its port and a
    setting by keyword, and one taking only a port, When Ports as keywords
    runs, Then a finding names the use case whose port comes before its
    values, and the port; a port after a value, or with no value to
    follow, is clean."""
    files = {USE: b"x\n" * 9, STORE: b"x\n" * 9}
    definitions = [
        *port(STORE, "Store", 1),
        function(USE, "kwb", 1, (keyword("store", "Store"), keyword("order", "Order"))),
        function(
            USE,
            "fine",
            2,
            (
                value("order", "Order"),
                keyword("store", "Store"),
                keyword("limit", "int"),
            ),
        ),
        function(USE, "only", 3, (keyword("store", "Store"),)),
    ]

    report = measure_with(files, facts(definitions))

    found = {(f.unit.symbol, f.subject) for f in _of(report, "Ports as keywords")}
    assert found == {("kwb", "store: Store")}


def test_measure_with_a_use_case_constructing_a_fake_adapter_finds_it() -> None:
    """Given an adapters-layer class named as a fake (FakeHttp) and a use
    case in production code that takes it and constructs it, When No
    self-wiring and Values in and out run, Then each names the use case
    and the fake: a fake's name exempts it only where the design says (a
    test, the Swap check), never a use case wiring it."""
    files = {USE: b"x\n" * 9, STORE: b"x\n" * 9, FS: b"x\n" * 9}
    definitions = [
        *port(STORE, "Store", 1),
        type_(FS, "FakeHttp", 1, bases=("Store",)),
        function(USE, "wired", 1, (value("f", "FakeHttp"),), end=3),
    ]
    calls = (Call(USE, 2, "wired", "FakeHttp"),)

    report = measure_with(files, facts(definitions, calls=calls))

    wired = {(f.unit.symbol, f.subject) for f in _of(report, "No self-wiring")}
    carried = {(f.unit.symbol, f.subject) for f in _of(report, "Values in and out")}
    assert wired == {("wired", "FakeHttp")}
    assert carried == {("wired", "f: FakeHttp")}


def test_measure_with_a_use_case_raising_an_adapter_error_is_clean() -> None:
    """Given an adapters module holding a concrete adapter of a port, an
    exception and an enum, and a use case that constructs the adapter
    through an import alias (`FsStore as Fs`), raises the exception and
    builds the enum, When No self-wiring runs, Then the one finding names
    the aliased construction: only a type implementing a port is a
    concrete adapter, and an alias is resolved to what it imports."""
    files = {USE: b"x\n" * 9, STORE: b"x\n" * 9, FS: b"x\n" * 12}
    definitions = [
        *port(STORE, "Store", 1),
        type_(FS, "FsStore", 1, bases=("Store",)),
        type_(FS, "StoreError", 4, bases=("Exception",)),
        type_(FS, "Mode", 7, bases=("enum.Enum",)),
        function(USE, "close", 2, end=6),
    ]
    calls = (
        Call(USE, 3, "close", "Fs"),
        Call(USE, 4, "close", "StoreError"),
        Call(USE, 5, "close", "Mode"),
    )
    bindings = (Binding(USE, 1, None, "Fs", "app.adapters.fs.FsStore"),)

    report = measure_with(files, facts(definitions, calls=calls, bindings=bindings))

    found = {
        (f.unit.symbol, f.subject, f.evidence.line)
        for f in _of(report, "No self-wiring")
    }
    assert found == {("close", "Fs", 3)}
