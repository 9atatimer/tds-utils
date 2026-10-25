"""The Layered quality's rule checks -- Trace, Purity's rule part, Wiring,
Anatomy -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface)."""

from __future__ import annotations

import time
from dataclasses import replace

from adherence.domain.finding import Finding
from adherence.domain.model import (
    Body,
    Call,
    CodeModel,
    Definition,
    Layer,
    Parameter,
    Signature,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Vocabulary
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    SurfaceRow,
    UseCase,
)
from adherence.domain.report import Report
from tests.measure_kit import VOCABULARY, declared, measure_with

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


def test_measure_behavior_row_naming_no_action_or_observation_is_found() -> None:
    """Given behavior rows with no When, with an empty When, and with no Then,
    each carried by its use case, When Trace runs, Then a finding names each
    row and the record, and a row with both is not found."""
    rows = {
        "Orders exist": "Given orders.",
        "Orders wait": "Given orders, When , Then they wait",
        "Orders move": "Given orders, When they are moved",
        CLOSED: SCENARIO,
    }
    behaviors = tuple(
        Behavior(name, scenario, DESIGN, line)
        for line, (name, scenario) in enumerate(rows.items(), start=20)
    )
    records = DesignRecords(
        behaviors=behaviors,
        use_cases=(
            UseCase(
                "close_order", Signature(_parameters("order"), None), ARCHITECTURE, 3
            ),
        ),
        surface=tuple(
            SurfaceRow(b.name, "close_order", ARCHITECTURE, 3) for b in behaviors
        ),
    )
    facts = CodeModel(
        definitions=(_function(USE, "close_order", _parameters("order")),)
    )

    report = measure_with({USE: b"x = 1\n"}, facts, records=records)

    untraceable = {f.unit.symbol: f for f in _of(report, "Trace")}
    assert set(untraceable) == {"Orders exist", "Orders wait", "Orders move"}
    for finding in untraceable.values():
        assert finding.unit.path == DESIGN
        assert "no nameable" in finding.subject
    assert untraceable["Orders exist"].evidence.line == 20


def _one_row(scenario: str) -> DesignRecords:
    """Records stating one behavior with that scenario, carried by its use
    case, so only the row's own text can make it untraceable."""
    return DesignRecords(
        behaviors=(Behavior(CLOSED, scenario, DESIGN, 9),),
        use_cases=(
            UseCase(
                "close_order", Signature(_parameters("order"), None), ARCHITECTURE, 3
            ),
        ),
        surface=(SurfaceRow(CLOSED, "close_order", ARCHITECTURE, 3),),
    )


def _traced(scenario: str) -> list[Finding]:
    facts = CodeModel(
        definitions=(_function(USE, "close_order", _parameters("order")),)
    )
    report = measure_with({USE: b"x = 1\n"}, facts, records=_one_row(scenario))
    return _of(report, "Trace")


# DESIGN.ARCH-ADHERENCE.md, Behaviors: "A test that skips the Then is found".
SKIPS_THE_THEN = (
    "Given a kept test that calls its use case but does not assert the row's "
    "Then, When Then asserted runs and the judge's answer is above its "
    "threshold, Then a finding names the test and the behavior, with its "
    "confidence"
)


def test_measure_row_whose_when_names_the_word_then_is_traced() -> None:
    """Given the approved row "A test that skips the Then is found", whose
    When clause names the check Then asserted, carried by its use case, When
    Trace runs, Then the row is read whole and there is no Trace finding."""
    assert _traced(SKIPS_THE_THEN) == []


def test_measure_row_of_repeated_whens_is_read_in_linear_time() -> None:
    """Given a 100 KB row of nothing but "When " (records are untrusted
    data), When Trace runs, Then the row is untraceable and is read in well
    under a second -- the lazy When/Then regex took ten seconds here."""
    started = time.perf_counter()

    (finding,) = _traced("When " * 20_000)

    assert "no nameable" in finding.subject
    assert time.perf_counter() - started < 1.0


STORE = "src/app/ports/store.py"


def _purity_vocabulary() -> Vocabulary:
    return replace(
        VOCABULARY, clocks=frozenset({"Clock"}), callables=frozenset({"Callable"})
    )


def _type(path: str, name: str, line: int) -> Definition:
    unit = Unit(path, UnitKind.TYPE, name, line, line + 2, None)
    return Definition(unit, None, Body("", (), ()), ("Protocol",), (), None, False)


def _stub_method(path: str, owner: str, name: str, line: int) -> Definition:
    unit = Unit(path, UnitKind.FUNCTION, f"{owner}.{name}", line, line, None)
    return Definition(unit, None, Body("...", ("...",), ()), (), (), owner, False)


def _annotated(*pairs: tuple[str, str]) -> tuple[Parameter, ...]:
    return tuple(Parameter(name, kind, False, False) for name, kind in pairs)


def test_measure_domain_function_taking_a_port_or_a_clock_is_found() -> None:
    """Given domain functions that take a port and a clock, one that takes a
    callable, and a use case that takes the port, When Purity runs, Then a
    finding names each domain function and the parameter, the port's
    reaching the ports layer; the callable is coverage for the judged part,
    and the use case is not found."""
    definitions = (
        _type(STORE, "Store", 1),
        _stub_method(STORE, "Store", "save", 2),
        _function(RULES, "price", _annotated(("order", "Order"), ("store", "Store"))),
        _function(RULES, "stamp", _annotated(("order", "Order"), ("now", "Clock")), 4),
        _function(
            RULES, "total", _annotated(("fetch", "Callable[[str], bytes]")), line=7
        ),
        _function(USE, "close_order", _annotated(("store", "ports.Store"))),
    )
    facts = CodeModel(definitions=definitions)
    files = {STORE: b"x\n", RULES: b"x\n", USE: b"x\n"}

    report = measure_with(files, facts, vocabulary=_purity_vocabulary())

    assert "Purity" in [c.name for c in report.ran]
    found = {(f.unit.symbol, f.layer, f.reached) for f in _of(report, "Purity")}
    assert found == {
        ("price", Layer.DOMAIN, Layer.PORTS),
        ("stamp", Layer.DOMAIN, None),
    }
    subjects = {f.unit.symbol: f.subject for f in _of(report, "Purity")}
    assert "store" in subjects["price"] and "now" in subjects["stamp"]
    judged = [c for c in report.coverage if c.check == "Purity"]
    assert [c.path for c in judged] == [RULES]
    assert "total" in judged[0].reason and "fetch" in judged[0].reason


FS = "src/app/adapters/fs.py"
ROOT = "src/app/container.py"
CLI = "src/app/cli.py"
TEST = "tests/test_use.py"
WIRED = b"""
[layers]
domain = ["src/app/domain/**"]
application = ["src/app/application/**"]
ports = ["src/app/ports/**"]
adapters = ["src/app/adapters/**"]
"composition root" = ["src/app/container.py", "src/app/cli.py"]
test = ["tests/**"]

[runtimes]
cli = ["src/app/**"]
"""


def _concrete(path: str, name: str, line: int = 1) -> tuple[Definition, ...]:
    """A type implementing the Store port by its method, over a mechanism."""
    unit = Unit(path, UnitKind.TYPE, name, line, line + 3, None)
    method = Unit(path, UnitKind.FUNCTION, f"{name}.save", line + 1, line + 2, None)
    return (
        Definition(unit, None, Body("", (), ()), (), (), None, False),
        Definition(
            method,
            Signature(_parameters("self order"), None),
            Body("write(order)", (), ()),
            (),
            (),
            name,
            False,
        ),
    )


def _wired(*extra: Definition) -> tuple[Definition, ...]:
    """The Store port, its concrete adapter FsStore and its fake FakeStore,
    and whatever else the test adds."""
    return (
        _type(STORE, "Store", 1),
        _stub_method(STORE, "Store", "save", 2),
        *_concrete(FS, "FsStore"),
        *_concrete(TEST, "FakeStore", 10),
        *extra,
    )


def _wiring_facts(
    definitions: tuple[Definition, ...], calls: tuple[Call, ...]
) -> CodeModel:
    return CodeModel(
        units=tuple(d.unit for d in definitions), definitions=definitions, calls=calls
    )


def test_measure_runtime_with_two_units_constructing_adapters_is_found() -> None:
    """Given a declared runtime with two units that construct concrete
    adapters, and a test that constructs a fake, When Wiring runs, Then one
    finding names both units."""
    definitions = _wired(
        _function(ROOT, "build", (), line=5),
        _function(CLI, "main", (), line=5),
        _function(TEST, "test_close", (), line=20),
    )
    calls = (
        Call(ROOT, 6, "build", "FsStore"),
        Call(CLI, 6, "main", "fs.FsStore"),
        Call(TEST, 21, "test_close", "FakeStore"),
    )
    files = {path: b"x\n" for path in (STORE, FS, ROOT, CLI, TEST)}

    report = measure_with(files, _wiring_facts(definitions, calls), declared(WIRED))

    assert "Wiring" in [c.name for c in report.ran]
    (second,) = _of(report, "Wiring")
    assert "cli" in second.subject
    assert f"{ROOT}:build" in second.subject and f"{CLI}:main" in second.subject


def test_measure_runtime_no_unit_constructs_adapters_for_is_a_disagreement() -> None:
    """Given a declared runtime one unit wires and a second declared runtime
    no unit constructs a concrete adapter for, When Wiring runs, Then one
    finding says the declaration and the code disagree and names the second
    runtime."""
    definitions = _wired(_function(ROOT, "build", (), line=5))
    calls = (Call(ROOT, 6, "build", "FsStore"),)
    files = {path: b"x\n" for path in (STORE, FS, ROOT)}
    declaration = declared(WIRED + b'worker = ["src/worker/**"]\n')

    report = measure_with(files, _wiring_facts(definitions, calls), declaration)

    (disagreement,) = _of(report, "Wiring")
    assert "worker" in disagreement.subject
    assert "disagree" in disagreement.subject
    assert disagreement.unit.path == "adherence.toml"


def test_measure_adapter_constructed_outside_the_root_is_found() -> None:
    """Given a use case and a test that each construct the concrete adapter,
    a test that constructs the fake, and the root that constructs it, When
    Wiring runs, Then a finding names the use case and the adapter, and one
    the test and the adapter (only a fake is exempt, by the design's Fake
    invariant), each reaching the adapters layer; the root and the fake are
    not found."""
    definitions = _wired(
        _function(ROOT, "build", (), line=5),
        _function(USE, "close_order", _parameters("order"), line=5),
        _function(TEST, "test_save", (), line=20),
        _function(TEST, "test_close", (), line=30),
    )
    calls = (
        Call(ROOT, 6, "build", "FsStore"),
        Call(USE, 6, "close_order", "FsStore"),
        Call(TEST, 21, "test_save", "fs.FsStore"),
        Call(TEST, 31, "test_close", "FakeStore"),
    )
    files = {path: b"x\n" for path in (STORE, FS, ROOT, USE, TEST)}

    report = measure_with(files, _wiring_facts(definitions, calls), declared(WIRED))

    below = {
        (f.unit.symbol, f.layer, f.subject)
        for f in _of(report, "Wiring")
        if f.reached is Layer.ADAPTERS
    }
    assert below == {
        ("close_order", Layer.APPLICATION, "FsStore"),
        ("test_save", Layer.TEST, "FsStore"),
    }


BAD = "bin/bad.py"
GOOD = "bin/good.py"
ONE_FILE_TOOLS = (
    b"[layers]\nregions = [\n"
    b'  { file = "bin/bad.py", layer = "composition root", lines = [1, 10] },\n'
    b'  { file = "bin/bad.py", layer = "domain", lines = [11, 20] },\n'
    b'  { file = "bin/bad.py", layer = "application", lines = [21, 30] },\n'
    b'  { file = "bin/good.py", layer = "domain", lines = [1, 5] },\n'
    b'  { file = "bin/good.py", layer = "adapters", lines = [6, 10] },\n'
    b'  { file = "bin/good.py", layer = "application", lines = [11, 15] },\n'
    b'  { file = "bin/good.py", layer = "composition root", lines = [16, 20] },\n'
    b"]\n"
)


def test_measure_file_whose_regions_run_out_of_order_is_found() -> None:
    """Given a file whose entry-point region comes before its rules and its
    workflow, and a file whose regions run rules, adapters, workflow, entry
    points, When Anatomy runs, Then one finding names the first file and its
    first region out of place, and the second is not found."""
    files = {BAD: b"x = 1\n" * 30, GOOD: b"x = 1\n" * 20}

    report = measure_with(files, CodeModel(), declared(ONE_FILE_TOOLS))

    assert "Anatomy" in [c.name for c in report.ran]
    (disorder,) = _of(report, "Anatomy")
    assert (disorder.unit.path, disorder.unit.kind) == (BAD, UnitKind.FILE)
    assert disorder.evidence.line == 11
    assert disorder.layer is Layer.DOMAIN
    assert "domain" in disorder.subject and "composition root" in disorder.subject


def test_measure_declaration_with_no_runtime_covers_wirings_per_runtime_half() -> None:
    """Given a declaration that declares no runtime, When Wiring runs, Then
    its per-runtime half is coverage saying why, never a clean result, and
    the half that needs no runtime still finds a construction below the root."""
    definitions = _wired(_function(USE, "close_order", _parameters("order"), line=5))
    calls = (Call(USE, 6, "close_order", "FsStore"),)
    files = {path: b"x\n" for path in (STORE, FS, USE)}
    unwired = WIRED.split(b"[runtimes]")[0]

    report = measure_with(files, _wiring_facts(definitions, calls), declared(unwired))

    assert [f.unit.symbol for f in _of(report, "Wiring")] == ["close_order"]
    (half,) = (c for c in report.coverage if c.check == "Wiring")
    assert "runtime" in half.reason
