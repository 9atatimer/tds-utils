"""domain/checks/layered.py -- rules, workflow and wiring are three jobs.

Trace, Purity's rule part, Wiring and Anatomy (DESIGN.ARCH-ADHERENCE.md,
The Qualities table: Layered), each a pure function over the CodeModel
and the design records. Purity's judged part, whether a callable a domain
function takes does I/O, is a question for the judge and reads as
coverage here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from adherence.domain.checks.hexagonal import implements, is_fake, is_port
from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    Runtime,
    layer_of,
    matches,
)
from adherence.domain.finding import Evidence, Finding, normalised
from adherence.domain.model import (
    Call,
    CodeModel,
    Definition,
    Layer,
    Parameter,
    Region,
    Signature,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    RecordsUnavailable,
    SurfaceRow,
    UseCase,
)

# --- Constants ---------------------------------------------------------------

TRACE = catalog_check("Trace")
# A row's action is its When clause and its observation its Then clause;
# each must hold a word for anything to trace to a function. The Then
# that opens the observation is the first after a word of the action, so
# a When clause may itself name the word (the check Then asserted). The
# keywords are read whatever their case.
WHEN = re.compile(r"\bwhen\b", re.IGNORECASE)
THEN = re.compile(r"\bthen\b", re.IGNORECASE)
WORD = re.compile(r"\w")
UNTRACEABLE = "the row has no nameable action (When) or observation (Then)"
NO_BEHAVIORS = (
    "the design record states no behaviors (no Behaviors section with a "
    "table row), so there is no contract to trace"
)
PURITY = catalog_check("Purity")
NAME = re.compile(r"[A-Za-z_]\w*")
# An annotation's text read as tokens: a string literal, a dotted name, or
# a bracket. A string is a forward reference unless it sits inside the
# brackets of a Literal, whose values are data.
ANNOTATION_TOKEN = re.compile(
    r"""(?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
    r"|(?P<name>[A-Za-z_][\w.]*)|(?P<open>\[)|(?P<close>\])",
    re.DOTALL,
)
LITERAL = "Literal"
DOES_IO_UNASKED = "the judged part (does_io) is not asked in this suite version"
WIRING = catalog_check("Wiring")
NO_RUNTIME = "the per-runtime half needs a declared runtime; the declaration has none"
ANATOMY = catalog_check("Anatomy")
# The coding skill's file anatomy, as the layers of a file's regions:
# predicates and pure helpers, then the effectful helpers, then the flow
# functions, then the entry points.
ANATOMY_ORDER: tuple[Layer, ...] = (
    Layer.DOMAIN,
    Layer.PORTS,
    Layer.ADAPTERS,
    Layer.APPLICATION,
    Layer.COMPOSITION_ROOT,
    Layer.TEST,
)


@dataclass(frozen=True, slots=True)
class _Construction:
    """One call that constructs a concrete adapter: the unit making it and
    the layer of the line it is on."""

    unit: Unit
    layer: Layer | None
    adapter: str
    call: Call


# A use case's home: its name and its parameter names, in order. The
# keyword-only shape is not compared (architecture Q1 stays open).
Home = tuple[str, tuple[str, ...]]

# --- Predicates --------------------------------------------------------------


def is_use_case_function(definition: Definition) -> bool:
    """Whether a definition can carry a use case: a function at module level
    in the application layer."""
    return (
        definition.unit.kind is UnitKind.FUNCTION
        and definition.unit.layer is Layer.APPLICATION
        and definition.signature is not None
        and definition.parent is None
        and not definition.nested
    )


def is_traceable(scenario: str) -> bool:
    """Whether a behavior row names an action and an observation: a When
    clause and a Then clause after it, each with a word in it. Each search
    starts where the last ended, so the read is linear in the row."""
    when = WHEN.search(scenario)
    action = WORD.search(scenario, when.end()) if when else None
    then = THEN.search(scenario, action.end()) if action else None
    return then is not None and WORD.search(scenario, then.end()) is not None


def is_rule(definition: Definition) -> bool:
    """Whether a definition is a domain function or method."""
    return (
        definition.unit.kind is UnitKind.FUNCTION
        and definition.unit.layer is Layer.DOMAIN
        and definition.signature is not None
    )


def is_in_runtime(path: str, runtime: Runtime) -> bool:
    """Whether a path is one of the runtime's units."""
    return any(matches(pattern, path) for pattern in runtime.patterns)


# --- Pure helpers ------------------------------------------------------------


def parameter_names(signature: Signature) -> tuple[str, ...]:
    return tuple(p.name for p in signature.parameters)


def _home_of(name: str, signature: Signature) -> Home:
    return name, parameter_names(signature)


def _shown(home: Home) -> str:
    name, parameters = home
    return f"{name}({', '.join(parameters)})"


def _homes(model: CodeModel) -> dict[Home, list[Definition]]:
    """Every application function that can carry a use case, by its home."""
    homes: dict[Home, list[Definition]] = {}
    for d in model.definitions:
        if is_use_case_function(d) and d.signature is not None:
            name = (d.unit.symbol or "").rpartition(".")[2]
            homes.setdefault(_home_of(name, d.signature), []).append(d)
    return homes


def _homeless(
    behavior: Behavior,
    rows: Mapping[str, SurfaceRow],
    use_cases: Mapping[str, UseCase],
    homes: Mapping[Home, Sequence[Definition]],
) -> str | None:
    """Why a behavior has no home, or None when one application unit
    carries it by the surface's signature. A row nothing could trace is a
    finding against the record."""
    if not is_traceable(behavior.scenario):
        return UNTRACEABLE
    row = rows.get(normalised(behavior.name))
    if row is None:
        return "the use-case surface has no row for it"
    if row.use_case is None:
        return "its use-case surface row names no use case"
    use_case = use_cases.get(row.use_case)
    if use_case is None:
        return f"the use-case surface gives {row.use_case} no signature"
    home = _home_of(use_case.name, use_case.signature)
    found = homes.get(home, ())
    if not found:
        return f"no application unit is {_shown(home)}"
    if len(found) > 1:
        where = ", ".join(sorted(d.unit.path for d in found))
        return f"{len(found)} application units are {_shown(home)}: {where}"
    return None


def _against(behavior: Behavior, why: str) -> Finding:
    """A Trace finding naming the behavior and the record it came from."""
    unit = Unit(
        behavior.path,
        UnitKind.BEHAVIOR,
        behavior.name,
        behavior.line,
        behavior.line,
        None,
    )
    return Finding(
        TRACE,
        unit,
        None,
        f"{behavior.name}: {why}",
        Evidence(behavior.path, behavior.line, behavior.name),
    )


def trace(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every design behavior resolves to one application unit, by the
    use-case surface's signature."""
    if not declaration.declared:
        return undeclared(TRACE.name)
    if isinstance(records, RecordsUnavailable):
        return CheckOutcome(
            coverage=(Coverage(records.reason, check=TRACE.name),), ran=False
        )
    if not records.behaviors:
        named = declaration.records.design if declaration.records else None
        reason = f"{named}: {NO_BEHAVIORS}" if named else NO_BEHAVIORS
        return CheckOutcome(coverage=(Coverage(reason, check=TRACE.name),), ran=False)
    rows = {normalised(r.behavior): r for r in records.surface}
    use_cases = {u.name: u for u in records.use_cases}
    homes = _homes(model)
    findings = [
        _against(behavior, why)
        for behavior in records.behaviors
        if (why := _homeless(behavior, rows, use_cases, homes)) is not None
    ]
    return CheckOutcome(tuple(findings))


def _methods(model: CodeModel) -> dict[tuple[str, str], list[Definition]]:
    """Each type's methods, keyed by the type's path and symbol."""
    methods: dict[tuple[str, str], list[Definition]] = {}
    for d in model.definitions:
        if d.unit.kind is UnitKind.FUNCTION and d.parent is not None:
            methods.setdefault((d.unit.path, d.parent), []).append(d)
    return methods


def _own(
    definition: Definition, methods: Mapping[tuple[str, str], list[Definition]]
) -> list[Definition]:
    return methods.get((definition.unit.path, definition.unit.symbol or ""), [])


def _short(definition: Definition) -> str:
    return (definition.unit.symbol or "").rpartition(".")[2]


def _port_names(model: CodeModel) -> frozenset[str]:
    """The names of the ports the model defines."""
    methods = _methods(model)
    return frozenset(
        _short(d)
        for d in model.definitions
        if d.unit.kind is UnitKind.TYPE and is_port(d, _own(d, methods))
    )


def _opens_literal(previous: str, inside: Sequence[bool]) -> bool:
    """Whether a bracket after the token `previous` holds Literal values:
    it subscripts Literal, or sits inside brackets that do."""
    return previous.rpartition(".")[2] == LITERAL or bool(inside and inside[-1])


def annotation_names(parameter: Parameter) -> frozenset[str]:
    """Every name a parameter's annotation mentions, dotted parts apart: a
    string forward reference by the names it holds, a Literal's values not
    at all."""
    names: set[str] = set()
    inside: list[bool] = []
    previous = ""
    for token in ANNOTATION_TOKEN.finditer(parameter.annotation or ""):
        kind, text = token.lastgroup, token.group()
        if kind == "open":
            inside.append(_opens_literal(previous, inside))
        elif kind == "close" and inside:
            inside.pop()
        elif kind == "string" and not (inside and inside[-1]):
            names.update(NAME.findall(text[1:-1]))
        elif kind == "name":
            names.update(NAME.findall(text))
        previous = text if kind == "name" else ""
    return frozenset(names)


def _taken(
    rule: Definition,
    parameter: Parameter,
    ports: frozenset[str],
    vocabulary: Vocabulary,
) -> Finding | Coverage | None:
    """What one parameter of a domain function makes of it: a finding for a
    port or a clock, coverage for a callable the judge would be asked about,
    or nothing."""
    names = annotation_names(parameter)
    unit = rule.unit
    evidence = Evidence(
        unit.path, unit.start, f"{parameter.name}: {parameter.annotation}"
    )
    if port := sorted(names & ports):
        subject = f"{parameter.name}: the port {port[0]}"
        return Finding(PURITY, unit, unit.layer, subject, evidence, reached=Layer.PORTS)
    if clock := sorted(names & vocabulary.clocks):
        subject = f"{parameter.name}: the clock {clock[0]}"
        return Finding(PURITY, unit, unit.layer, subject, evidence)
    if names & vocabulary.callables:
        return Coverage(
            f"{DOES_IO_UNASKED}: whether {unit.symbol}'s callable "
            f"{parameter.name} does I/O",
            check=PURITY.name,
            path=unit.path,
        )
    return None


def purity(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No domain unit takes a port or a clock; a callable it takes is left to
    the judged part."""
    if not declaration.declared:
        return undeclared(PURITY.name)
    ports = _port_names(model)
    taken = [
        _taken(rule, parameter, ports, parameters.vocabulary)
        for rule in model.definitions
        if is_rule(rule) and rule.signature is not None
        for parameter in rule.signature.parameters
    ]
    return CheckOutcome(
        tuple(t for t in taken if isinstance(t, Finding)),
        tuple(t for t in taken if isinstance(t, Coverage)),
    )


def _concrete_adapters(model: CodeModel, vocabulary: Vocabulary) -> frozenset[str]:
    """The names of the concrete adapters: types in the adapters layer that
    implement a port the model defines, over a mechanism, so not a fake."""
    methods = _methods(model)
    types = [d for d in model.definitions if d.unit.kind is UnitKind.TYPE]
    ports = [t for t in types if is_port(t, _own(t, methods))]
    return frozenset(
        _short(t)
        for t in types
        if t.unit.layer is Layer.ADAPTERS
        and not is_fake(t, vocabulary)
        and any(implements(t, _own(t, methods), p, _own(p, methods)) for p in ports)
    )


def _constructions(
    model: CodeModel, declaration: Declaration, adapters: frozenset[str]
) -> list[_Construction]:
    """Every call that constructs a concrete adapter, with the unit making it:
    the definition it sits in, or its file at module level."""
    units = {(d.unit.path, d.unit.symbol): d.unit for d in model.definitions}
    found: list[_Construction] = []
    for call in model.calls:
        adapter = call.callee.rpartition(".")[2]
        if adapter not in adapters:
            continue
        unit = units.get((call.path, call.within)) or model.unit_at(
            call.path, call.line
        )
        if unit is None:
            continue
        layer = layer_of(call.path, call.line, declaration, model.regions)
        found.append(_Construction(unit, layer, adapter, call))
    return found


def _named(unit: Unit) -> str:
    return f"{unit.path}:{unit.symbol}" if unit.symbol else unit.path


def _roots(
    runtime: Runtime, constructions: Sequence[_Construction]
) -> dict[Unit, list[_Construction]]:
    """The runtime's units that construct concrete adapters, in order; a
    test is no part of a runtime."""
    roots: dict[Unit, list[_Construction]] = {}
    for c in sorted(constructions, key=lambda c: (c.unit.path, c.unit.start)):
        if c.layer is not Layer.TEST and is_in_runtime(c.unit.path, runtime):
            roots.setdefault(c.unit, []).append(c)
    return roots


def _no_root(runtime: Runtime) -> Finding:
    """A finding on the declaration: it declares a runtime that no unit
    wires, and the suite does not guess which of the two is right."""
    unit = Unit(DECLARATION_PATH, UnitKind.FILE, None, 1, 1, None)
    return Finding(
        WIRING,
        unit,
        None,
        f"runtime {runtime.name}: the declaration and the code disagree: no unit "
        "constructs a concrete adapter for it",
        Evidence(DECLARATION_PATH, 0, f"runtime {runtime.name}"),
    )


def _rooted(
    runtime: Runtime, roots: Mapping[Unit, Sequence[_Construction]]
) -> Finding | None:
    """A finding when a runtime has no root, or names every root of a
    runtime that has more than one."""
    if not roots:
        return _no_root(runtime)
    if len(roots) < 2:
        return None
    first, second = list(roots)[:2]
    call = roots[second][0].call
    named = ", ".join(_named(u) for u in roots)
    return Finding(
        WIRING,
        first,
        roots[first][0].layer,
        f"runtime {runtime.name}: {len(roots)} units construct concrete adapters: "
        f"{named}",
        Evidence(call.path, call.line, call.callee),
    )


def _below_root(construction: _Construction) -> Finding | None:
    """A finding naming a unit outside the composition-root layer and the
    concrete adapter it constructs; an uncovered unit is never checked."""
    if construction.layer in (None, Layer.COMPOSITION_ROOT):
        return None
    call = construction.call
    return Finding(
        WIRING,
        construction.unit,
        construction.layer,
        construction.adapter,
        Evidence(call.path, call.line, call.callee),
        reached=Layer.ADAPTERS,
    )


def wiring(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Per declared runtime, exactly one unit constructs concrete adapters,
    and no unit outside the composition-root layer constructs one."""
    if not declaration.declared:
        return undeclared(WIRING.name)
    adapters = _concrete_adapters(model, parameters.vocabulary)
    constructions = _constructions(model, declaration, adapters)
    findings = [
        finding
        for runtime in declaration.runtimes
        if (finding := _rooted(runtime, _roots(runtime, constructions))) is not None
    ]
    findings.extend(
        finding
        for construction in constructions
        if (finding := _below_root(construction)) is not None
    )
    unchecked = (
        () if declaration.runtimes else (Coverage(NO_RUNTIME, check=WIRING.name),)
    )
    return CheckOutcome(tuple(findings), unchecked)


def _out_of_place(regions: Sequence[Region]) -> tuple[Region, Region] | None:
    """The first region, in line order, whose layer comes earlier in the
    anatomy than a region above it, with that region; None when in order."""
    furthest: Region | None = None
    for region in sorted(regions, key=lambda r: (r.start, r.end)):
        rank = ANATOMY_ORDER.index(region.layer)
        if furthest is not None and rank < ANATOMY_ORDER.index(furthest.layer):
            return region, furthest
        if furthest is None or rank > ANATOMY_ORDER.index(furthest.layer):
            furthest = region
    return None


def anatomy(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """A file's regions run in the coding skill's file-anatomy order."""
    if not declaration.declared:
        return undeclared(ANATOMY.name)
    by_file: dict[str, set[Region]] = {}
    for region in (*declaration.layers.regions, *model.regions):
        by_file.setdefault(region.path, set()).add(region)
    files = {u.path: u for u in model.units if u.kind is UnitKind.FILE}
    findings: list[Finding] = []
    for path in sorted(by_file.keys() & files.keys()):
        disorder = _out_of_place(tuple(by_file[path]))
        if disorder is None:
            continue
        region, above = disorder
        findings.append(
            Finding(
                ANATOMY,
                files[path],
                region.layer,
                f"the {region.layer.value} region at line {region.start} follows "
                f"the {above.layer.value} region at line {above.start}",
                Evidence(path, region.start, region.layer.value),
            )
        )
    return CheckOutcome(tuple(findings))
