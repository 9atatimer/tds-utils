"""domain/checks/layered.py -- a unit depends only on its layer or one below it.

Arrow and Wiring (DESIGN.ARCH-ADHERENCE.md, The Qualities table: Layered),
each a pure function over the CodeModel. The order, bottom to top: domain,
ports, then application and adapters side by side, then the composition
root; a test may reach any layer.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from adherence.domain.checks.hexagonal import implements, is_fake, is_port
from adherence.domain.checks.outcome import NEEDS_DECLARATION, CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import (
    Declaration,
    Runtime,
    is_under,
    layer_of,
    matches,
)
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import (
    Call,
    CodeModel,
    Definition,
    ImportEdge,
    Layer,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

ARROW = catalog_check("Arrow")
_EVERY_LAYER = frozenset(Layer)
# The layers each layer may import: its own and the ones below it.
# application -> ports -> domain and adapters -> ports -> domain; the
# composition root and tests reach any.
INWARD: dict[Layer, frozenset[Layer]] = {
    Layer.DOMAIN: frozenset({Layer.DOMAIN}),
    Layer.PORTS: frozenset({Layer.DOMAIN, Layer.PORTS}),
    Layer.APPLICATION: frozenset({Layer.DOMAIN, Layer.PORTS, Layer.APPLICATION}),
    Layer.ADAPTERS: frozenset({Layer.DOMAIN, Layer.PORTS, Layer.ADAPTERS}),
    Layer.COMPOSITION_ROOT: _EVERY_LAYER,
    Layer.TEST: _EVERY_LAYER,
}
WIRING = catalog_check("Wiring")
NO_RUNTIME = "the per-runtime half needs a declared runtime; the declaration has none"
# An import's line as written, `from m import A as B, C`: the names it
# binds, read so a check compares the name an alias stands for. A
# statement wrapped over lines is read as far as its first line goes.
FROM_IMPORT = re.compile(r"\s*from\s+\S+\s+import\s+(?P<names>[^#]*)")
ALIAS = re.compile(r"(?P<name>[A-Za-z_]\w*)\s+as\s+(?P<alias>[A-Za-z_]\w*)")


@dataclass(frozen=True, slots=True)
class _Construction:
    """One call that constructs a concrete adapter: the unit making it and
    the layer of the line it is on."""

    unit: Unit
    layer: Layer | None
    adapter: str
    call: Call


# --- Predicates --------------------------------------------------------------


def is_inward(importer: Layer, imported: Layer) -> bool:
    """Whether an import from one layer into another crosses inward."""
    return imported in INWARD[importer]


def is_in_runtime(path: str, runtime: Runtime) -> bool:
    """Whether a path is one of the runtime's units: one its patterns
    match, outside every subtree a nearer declaration's
    [override.runtimes] voids it in."""
    return not any(is_under(path, d) for d in runtime.outside) and any(
        matches(pattern, path) for pattern in runtime.patterns
    )


# --- Pure helpers ------------------------------------------------------------


def import_aliases(model: CodeModel) -> dict[str, dict[str, str]]:
    """Each file's import aliases: the alias, and the name it stands for."""
    aliases: dict[str, dict[str, str]] = {}
    for edge in model.imports:
        imported = FROM_IMPORT.match(edge.text)
        if imported is None:
            continue
        for part in imported.group("names").strip(" ()").split(","):
            if bound := ALIAS.fullmatch(part.strip(" ()")):
                aliases.setdefault(edge.path, {})[bound["alias"]] = bound["name"]
    return aliases


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


def port_names(model: CodeModel) -> frozenset[str]:
    """The names of the ports the model defines."""
    methods = _methods(model)
    return frozenset(
        _short(d)
        for d in model.definitions
        if d.unit.kind is UnitKind.TYPE and is_port(d, _own(d, methods))
    )


def _outward(model: CodeModel, declaration: Declaration) -> list[Finding]:
    """Every import between two covered units that crosses outward."""
    findings: list[Finding] = []
    for edge in model.imports:
        if edge.imported_path is None:
            continue
        layer = layer_of(edge.path, edge.line, declaration, model.regions)
        reached = layer_of(edge.imported_path, None, declaration)
        unit = model.unit_at(edge.path, edge.line)
        if layer is None or reached is None or unit is None:
            continue
        if not is_inward(layer, reached):
            findings.append(
                Finding(
                    ARROW,
                    unit,
                    layer,
                    edge.imported,
                    Evidence(edge.path, edge.line, edge.text),
                    reached=reached,
                )
            )
    return findings


def strongly_connected(graph: Mapping[str, Sequence[str]]) -> list[list[str]]:
    """The strongly connected components of a graph, each sorted, by
    Tarjan's algorithm walked with an explicit stack (no recursion limit)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                index[node] = low[node] = len(index)
                stack.append(node)
                on_stack.add(node)
            successors = graph.get(node, ())
            if child < len(successors):
                work.append((node, child + 1))
                successor = successors[child]
                if successor not in index:
                    work.append((successor, 0))
                elif successor in on_stack:
                    low[node] = min(low[node], index[successor])
                continue
            if low[node] == index[node]:
                component: list[str] = []
                while not component or component[-1] != node:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                components.append(sorted(component))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return components


def cycle_through(
    start: str, members: Sequence[str], graph: Mapping[str, Sequence[str]]
) -> list[str]:
    """The shortest path from start back to itself through another member of
    one strongly connected component, start repeated at the end; a
    self-import is not such a path."""
    inside = set(members)
    previous: dict[str, str] = {}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for successor in graph.get(node, ()):
            if successor == start and node != start:
                path = [node]
                while path[-1] != start:
                    path.append(previous[path[-1]])
                return [*reversed(path), start]
            if successor in inside and successor not in previous:
                previous[successor] = node
                queue.append(successor)
    return [start]


def _import_graph(
    model: CodeModel, declaration: Declaration
) -> tuple[dict[str, list[str]], dict[tuple[str, str], ImportEdge]]:
    """The file-to-file import graph over the units a check may read (every
    file of an undeclared repository), and the first edge of each arc."""
    covered = {
        u.path for u in model.units if u.layer is not None or not declaration.declared
    }
    graph: dict[str, list[str]] = {}
    first: dict[tuple[str, str], ImportEdge] = {}
    for edge in model.imports:
        target = edge.imported_path
        if target is None or target == edge.path:
            continue
        if edge.path not in covered or target not in covered:
            continue
        if (edge.path, target) not in first:
            first[(edge.path, target)] = edge
            graph.setdefault(edge.path, []).append(target)
    return {k: sorted(v) for k, v in graph.items()}, first


def _cycles(model: CodeModel, declaration: Declaration) -> list[Finding]:
    """One finding per import cycle, on its first file, naming the cycle."""
    graph, first = _import_graph(model, declaration)
    findings: list[Finding] = []
    for members in strongly_connected(graph):
        if len(members) < 2:
            continue
        path = cycle_through(members[0], members, graph)
        edge = first[(path[0], path[1])]
        unit = model.unit_at(edge.path, edge.line)
        if unit is None:
            continue
        findings.append(
            Finding(
                ARROW,
                unit,
                layer_of(edge.path, edge.line, declaration, model.regions),
                " -> ".join(path),
                Evidence(edge.path, edge.line, edge.text),
            )
        )
    return findings


def arrow(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every import crosses inward and no import cycle exists. The cycle half
    needs no declaration; the inward half compares declared layers."""
    if not declaration.declared:
        inward = Coverage(f"the inward half {NEEDS_DECLARATION}", check=ARROW.name)
        return CheckOutcome(tuple(_cycles(model, declaration)), (inward,))
    return CheckOutcome((*_outward(model, declaration), *_cycles(model, declaration)))


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
    the definition it sits in, or its file at module level. A bare callee
    that is an import alias is read as the name it stands for."""
    units = {(d.unit.path, d.unit.symbol): d.unit for d in model.definitions}
    aliases = import_aliases(model)
    found: list[_Construction] = []
    for call in model.calls:
        adapter = call.callee.rpartition(".")[2]
        if "." not in call.callee:
            adapter = aliases.get(call.path, {}).get(adapter, adapter)
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


def _modules(model: CodeModel) -> dict[str, Unit]:
    """Each file's own unit, by path."""
    return {u.path: u for u in model.units if u.kind is UnitKind.FILE}


def _root_unit(construction: _Construction, modules: Mapping[str, Unit]) -> Unit:
    """The unit a construction counts toward as a root: in the
    composition-root layer the module, so one file that constructs adapters
    in several functions is one root (DESIGN.ARCH-ADHERENCE.md, Key
    Decisions, Wiring's unit in the composition root); elsewhere the unit
    making the call."""
    unit = construction.unit
    if construction.layer is not Layer.COMPOSITION_ROOT or unit.kind is UnitKind.FILE:
        return unit
    return modules.get(
        unit.path, Unit(unit.path, UnitKind.FILE, None, 1, unit.end, unit.layer)
    )


def _roots(
    runtime: Runtime,
    constructions: Sequence[_Construction],
    modules: Mapping[str, Unit],
) -> dict[Unit, list[_Construction]]:
    """The runtime's units that construct concrete adapters, in order, a
    composition-root file counted once as its module; a test is no part of
    a runtime."""
    roots: dict[Unit, list[_Construction]] = {}
    for c in sorted(constructions, key=lambda c: (c.unit.path, c.unit.start)):
        if c.layer is not Layer.TEST and is_in_runtime(c.unit.path, runtime):
            roots.setdefault(_root_unit(c, modules), []).append(c)
    return roots


def _no_root(runtime: Runtime) -> Finding:
    """A finding on the declaration: it declares a runtime that no unit
    wires, and the suite does not guess which of the two is right."""
    unit = Unit(runtime.source, UnitKind.FILE, None, 1, 1, None)
    return Finding(
        WIRING,
        unit,
        None,
        f"runtime {runtime.name}: the declaration and the code disagree: no unit "
        "constructs a concrete adapter for it",
        Evidence(runtime.source, 0, f"runtime {runtime.name}"),
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
    """A finding naming a unit outside the composition-root and test layers
    and the concrete adapter it constructs; an uncovered unit is never
    checked. A test that constructs a concrete adapter is that adapter's
    contract suite, which the testing skill requires (DESIGN.ARCH-ADHERENCE.md,
    Key Decisions, Wiring over the test layer)."""
    if construction.layer in (None, Layer.COMPOSITION_ROOT, Layer.TEST):
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
    """Per declared runtime, exactly one unit constructs concrete adapters --
    in the composition-root layer the unit is the module, however many of
    its functions construct -- and no unit outside the composition-root and
    test layers constructs one."""
    if not declaration.declared:
        return undeclared(WIRING.name)
    adapters = _concrete_adapters(model, parameters.vocabulary)
    constructions = _constructions(model, declaration, adapters)
    modules = _modules(model)
    findings = [
        finding
        for runtime in declaration.runtimes
        if (finding := _rooted(runtime, _roots(runtime, constructions, modules)))
        is not None
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
