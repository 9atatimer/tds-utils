"""domain/checks/hexagonal.py -- the core depends on no mechanism.

Grep, Arrow, Swap and Change (DESIGN.ARCH-ADHERENCE.md, The Qualities
table: Hexagonal), each a pure function over the CodeModel.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from adherence.domain.checks.outcome import NEEDS_DECLARATION, CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import (
    AccessKind,
    CodeModel,
    Definition,
    ImportEdge,
    Layer,
    ReferenceKind,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable, Seam

# --- Constants ---------------------------------------------------------------

GREP = catalog_check("Grep")
ARROW = catalog_check("Arrow")
SWAP = catalog_check("Swap")
CHANGE = catalog_check("Change")
# Where a seam's port, policy or parameter may live: anywhere but an
# adapter or a test.
SEAM_LAYERS = frozenset(
    {Layer.DOMAIN, Layer.PORTS, Layer.APPLICATION, Layer.COMPOSITION_ROOT}
)
CORE = frozenset({Layer.DOMAIN, Layer.APPLICATION})
_EVERY_LAYER = frozenset(Layer)
# The layers each layer may import: cli -> application -> domain and
# adapters -> ports -> domain; the composition root and tests reach any.
INWARD: dict[Layer, frozenset[Layer]] = {
    Layer.DOMAIN: frozenset({Layer.DOMAIN}),
    Layer.PORTS: frozenset({Layer.DOMAIN, Layer.PORTS}),
    Layer.APPLICATION: frozenset({Layer.DOMAIN, Layer.PORTS, Layer.APPLICATION}),
    Layer.ADAPTERS: frozenset({Layer.DOMAIN, Layer.PORTS, Layer.ADAPTERS}),
    Layer.COMPOSITION_ROOT: _EVERY_LAYER,
    Layer.TEST: _EVERY_LAYER,
}


@dataclass(frozen=True, slots=True)
class _Hit:
    """A mechanism named at one line: what is named and the text naming it."""

    path: str
    line: int
    subject: str
    text: str


# --- Predicates --------------------------------------------------------------


def names_vendor(module: str, vocabulary: Vocabulary) -> bool:
    """Whether a module, or a dotted prefix of it, is a vendor, an SDK, the
    filesystem or the network."""
    parts = module.split(".")
    return any(
        ".".join(parts[:end]) in vocabulary.vendors for end in range(1, len(parts) + 1)
    )


def is_inward(importer: Layer, imported: Layer) -> bool:
    """Whether an import from one layer into another crosses inward."""
    return imported in INWARD[importer]


def is_model_id(text: str, vocabulary: Vocabulary) -> bool:
    """Whether a string literal names a model."""
    lowered = text.lower()
    return any(lowered.startswith(prefix) for prefix in vocabulary.model_ids)


# --- Pure helpers ------------------------------------------------------------


def _mechanisms(model: CodeModel, vocabulary: Vocabulary) -> list[_Hit]:
    """Every vendor import, environment read and model id in the model."""
    return [
        *(
            _Hit(e.path, e.line, e.imported, e.text)
            for e in model.imports
            if e.imported_path is None and names_vendor(e.imported, vocabulary)
        ),
        *(
            _Hit(a.path, a.line, a.target, a.target)
            for a in model.accesses
            if a.kind is AccessKind.ENVIRONMENT
        ),
        *(
            _Hit(r.path, r.line, r.text, r.text)
            for r in model.references
            if r.kind is ReferenceKind.STRING and is_model_id(r.text, vocabulary)
        ),
    ]


def grep(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No domain or application unit names a vendor, an SDK, the
    environment, the filesystem, the network, or a model id."""
    if not declaration.declared:
        return undeclared(GREP.name)
    findings: list[Finding] = []
    for hit in _mechanisms(model, parameters.vocabulary):
        layer = layer_of(hit.path, hit.line, declaration, model.regions)
        unit = model.unit_at(hit.path, hit.line)
        if layer in CORE and unit is not None:
            findings.append(
                Finding(
                    GREP,
                    unit,
                    layer,
                    hit.subject,
                    Evidence(hit.path, hit.line, hit.text),
                )
            )
    return CheckOutcome(tuple(findings))


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


def _name(definition: Definition) -> str:
    return (definition.unit.symbol or "").rpartition(".")[2]


def _methods(model: CodeModel) -> dict[tuple[str, str], list[Definition]]:
    """Each type's methods, keyed by the type's path and symbol."""
    methods: dict[tuple[str, str], list[Definition]] = {}
    for d in model.definitions:
        if d.unit.kind is UnitKind.FUNCTION and d.parent is not None:
            methods.setdefault((d.unit.path, d.parent), []).append(d)
    return methods


def _types(model: CodeModel) -> list[Definition]:
    return [d for d in model.definitions if d.unit.kind is UnitKind.TYPE]


def is_port(definition: Definition, methods: Sequence[Definition]) -> bool:
    """Whether a type is a port: in the ports layer, declaring methods and
    implementing none of them."""
    return (
        definition.unit.layer is Layer.PORTS
        and bool(methods)
        and all(m.body.stub_markers for m in methods)
    )


def _method_names(methods: Sequence[Definition]) -> set[str]:
    return {_name(m) for m in methods if not _name(m).startswith("__")}


def implements(
    candidate: Definition,
    candidate_methods: Sequence[Definition],
    port: Definition,
    port_methods: Sequence[Definition],
) -> bool:
    """Whether a type implements a port: it names the port as a base, or it
    has every method the port declares."""
    if candidate is port:
        return False
    if any(base.rpartition(".")[2] == _name(port) for base in candidate.bases):
        return True
    wanted = _method_names(port_methods)
    return bool(wanted) and wanted <= _method_names(candidate_methods)


def is_fake(definition: Definition, vocabulary: Vocabulary) -> bool:
    """Whether an implementation is a fake: a test unit, or a type whose name
    carries one of the vocabulary's fake prefixes."""
    return definition.unit.layer is Layer.TEST or any(
        _name(definition).startswith(prefix) for prefix in vocabulary.fakes
    )


def swap(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every port has at least one fake, anywhere in the repository."""
    if not declaration.declared:
        return undeclared(SWAP.name)
    methods = _methods(model)
    types = _types(model)
    findings: list[Finding] = []
    for port in types:
        own = methods.get((port.unit.path, port.unit.symbol or ""), [])
        if not is_port(port, own):
            continue
        faked = any(
            is_fake(t, parameters.vocabulary)
            and implements(
                t, methods.get((t.unit.path, t.unit.symbol or ""), []), port, own
            )
            for t in types
        )
        if not faked:
            unit = port.unit
            findings.append(
                Finding(
                    SWAP,
                    unit,
                    unit.layer,
                    _name(port),
                    Evidence(unit.path, unit.start, _name(port)),
                )
            )
    return CheckOutcome(tuple(findings))


def _seam_finding(seam: Seam, subject: str) -> Finding:
    unit = Unit(seam.path, UnitKind.SEAM, seam.name, seam.line, seam.line, None)
    return Finding(
        CHANGE, unit, None, subject, Evidence(seam.path, seam.line, seam.name)
    )


def change(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every seam the architecture record names exists as exactly one port,
    policy or parameter: one type of that name outside the adapters and the
    tests."""
    if not declaration.declared:
        return undeclared(CHANGE.name)
    if isinstance(records, RecordsUnavailable):
        return CheckOutcome(
            coverage=(Coverage(records.reason, check="Change"),), ran=False
        )
    homes: dict[str, list[str]] = {}
    for t in _types(model):
        if t.unit.layer in SEAM_LAYERS:
            homes.setdefault(_name(t), []).append(t.unit.path)
    findings: list[Finding] = []
    for seam in records.seams:
        found = homes.get(seam.name, [])
        if not found:
            findings.append(_seam_finding(seam, f"{seam.name}: no {seam.kind.value}"))
        elif len(found) > 1:
            where = ", ".join(sorted(found))
            findings.append(_seam_finding(seam, f"{seam.name}: defined in {where}"))
    return CheckOutcome(tuple(findings))
