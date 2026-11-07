"""domain/checks/law.py -- every function is logic, action or workflow.

Todd's LAW (DESIGN.ARCH-ADHERENCE.md, The Qualities table: LAW): a
function computes a value (logic), changes something (action) or calls
other functions in order (workflow), and never two of the three. Purity's
rule part and Anatomy are pure functions over the CodeModel; Purity's
judged part, whether a callable a domain function takes does I/O, and
Kind, whether a function is of two kinds, are questions for the judge.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from adherence.domain.checks.layered import import_aliases, port_names
from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import (
    Call,
    CodeModel,
    Definition,
    Layer,
    Parameter,
    Region,
    UnitKind,
)
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.questions import DOES_IO, KIND, Ask, definition_text
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

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
NOT_CALLED = "nowhere the analyzer resolved"
ANATOMY = catalog_check("Anatomy")
KIND_CHECK = catalog_check("Kind")
# Kind asks about every function in a layer the LAW governs: production
# code. A test is workflow around an assertion by design and is not asked.
GOVERNED: frozenset[Layer] = frozenset(Layer) - {Layer.TEST}
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

# --- Predicates --------------------------------------------------------------


def is_rule(definition: Definition) -> bool:
    """Whether a definition is a domain function or method."""
    return (
        definition.unit.kind is UnitKind.FUNCTION
        and definition.unit.layer is Layer.DOMAIN
        and definition.signature is not None
    )


# --- Pure helpers ------------------------------------------------------------


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


def _call_sites(model: CodeModel) -> dict[tuple[str, str], list[Call]]:
    """Every call that resolves to a repository definition, by its path and
    symbol."""
    sites: dict[tuple[str, str], list[Call]] = {}
    for call in model.calls:
        target = call.target
        if target is not None and target.path is not None and target.symbol:
            sites.setdefault((target.path, target.symbol), []).append(call)
    return sites


def _does_io_ask(rule: Definition, parameter: Parameter, sites: Sequence[Call]) -> Ask:
    """The does_io question about one callable a domain function takes: the
    function as the unit's text, the parameter and where the function is
    called from as its data."""
    unit = rule.unit
    called = "; ".join(f"{c.path}:{c.line} in {c.within}" for c in sites)
    return Ask(
        check=PURITY,
        question=DOES_IO,
        unit=unit,
        layer=unit.layer,
        subject=f"{unit.symbol}: its callable {parameter.name} does I/O",
        evidence=Evidence(
            unit.path, unit.start, f"{parameter.name}: {parameter.annotation}"
        ),
        text=definition_text(rule),
        context=(
            f"the callable parameter: {parameter.name}: {parameter.annotation}\n"
            f"{unit.symbol} is called from: {called or NOT_CALLED}"
        ),
    )


def _taken(
    rule: Definition,
    parameter: Parameter,
    ports: frozenset[str],
    vocabulary: Vocabulary,
    aliases: Mapping[str, str],
    sites: Mapping[tuple[str, str], Sequence[Call]],
) -> Finding | Ask | None:
    """What one parameter of a domain function makes of it: a finding for a
    port or a clock, the does_io question for a callable, or nothing. An
    import alias is read as the name it stands for."""
    names = frozenset(aliases.get(n, n) for n in annotation_names(parameter))
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
        return _does_io_ask(
            rule, parameter, sites.get((unit.path, unit.symbol or ""), [])
        )
    return None


def purity(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No domain unit takes a port or a clock; whether a callable it takes
    does I/O is the judged part's question."""
    if not declaration.declared:
        return undeclared(PURITY.name)
    ports = port_names(model)
    aliases = import_aliases(model)
    sites = _call_sites(model)
    taken = [
        _taken(
            rule,
            parameter,
            ports,
            parameters.vocabulary,
            aliases.get(rule.unit.path, {}),
            sites,
        )
        for rule in model.definitions
        if is_rule(rule) and rule.signature is not None
        for parameter in rule.signature.parameters
    ]
    return CheckOutcome(
        tuple(t for t in taken if isinstance(t, Finding)),
        questions=tuple(t for t in taken if isinstance(t, Ask)),
    )


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


def _kind_ask(definition: Definition) -> Ask:
    unit = definition.unit
    layer = unit.layer
    return Ask(
        check=KIND_CHECK,
        question=KIND,
        unit=unit,
        layer=layer,
        subject=f"{unit.symbol}: two of logic, action and workflow in one function",
        evidence=Evidence(unit.path, unit.start, unit.symbol or ""),
        text=definition_text(definition),
        context=f"declared layer: {layer.value if layer else ''}",
    )


def kind(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Asks the judge, of every function in a governed layer, whether it does
    two of logic, action and workflow; it finds nothing by itself."""
    if not declaration.declared:
        return undeclared(KIND_CHECK.name)
    return CheckOutcome(
        questions=tuple(
            _kind_ask(d)
            for d in model.definitions
            if d.unit.kind is UnitKind.FUNCTION
            and not d.nested
            and d.unit.layer in GOVERNED
        )
    )
