"""The extracted graph as a value, its JSON contract (schema layer-graph/1),
and the short human summary."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from layer_graph.domain.declaration import LAYER_ORDER
from layer_graph.domain.graph import is_outward

# --- Constants ---------------------------------------------------------------

SCHEMA = "layer-graph/1"


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Node:
    """One (layer, context) node and the unit files in it."""

    id: str
    layer: str
    context: str
    files: tuple[str, ...]
    runtimes: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        """The node in the JSON contract."""
        return {
            "id": self.id,
            "layer": self.layer,
            "context": self.context,
            "files": list(self.files),
            "fileCount": len(self.files),
            "runtimes": list(self.runtimes),
        }


@dataclass(frozen=True, slots=True)
class Edge:
    """Imports from one node to another, counted by import statement."""

    source: str
    target: str
    imports: int
    direction: str

    def to_json(self) -> dict[str, object]:
        """The edge in the JSON contract."""
        return {
            "from": self.source,
            "to": self.target,
            "imports": self.imports,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class Stats:
    """Unit files read, import statements in them, and how many of those
    reached no file in the repository."""

    files: int
    imports: int
    unresolved: int


@dataclass(frozen=True)
class LayerGraph:
    """A repository's layer graph and its findings."""

    root: str
    repo: str | None
    commit: str | None
    declarations: tuple[str, ...]
    runtimes: Mapping[str, tuple[str, ...]]
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    cycles: tuple[tuple[str, ...], ...]
    unassigned: tuple[str, ...]
    stats: Stats = field(default_factory=lambda: Stats(0, 0, 0))

    @property
    def outward(self) -> tuple[Edge, ...]:
        """The edges that point outward: dependency-rule violations."""
        return tuple(e for e in self.edges if is_outward(e.direction))

    def to_json(self) -> dict[str, object]:
        """The graph in the layer-graph/1 JSON contract, keys in order."""
        return {
            "schema": SCHEMA,
            "root": self.root,
            "repo": self.repo,
            "commit": self.commit,
            "declarations": list(self.declarations),
            "layers": list(LAYER_ORDER),
            "runtimes": {name: list(ids) for name, ids in self.runtimes.items()},
            "nodes": [n.to_json() for n in self.nodes],
            "edges": [e.to_json() for e in self.edges],
            "findings": {
                "outward": [
                    {"from": e.source, "to": e.target, "imports": e.imports}
                    for e in self.outward
                ],
                "cycles": [list(c) for c in self.cycles],
                "unassigned": list(self.unassigned),
            },
            "stats": {
                "files": self.stats.files,
                "imports": self.stats.imports,
                "unresolved": self.stats.unresolved,
            },
        }


# --- Pure helpers: the summary ---------------------------------------------------


def _table(rows: list[tuple[str, ...]]) -> list[str]:
    if not rows:
        return ["  (none)"]
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return [
        "  "
        + "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]


def _cycle_line(cycle: tuple[str, ...]) -> str:
    joiner = " <-> " if len(cycle) == 2 else " -> "
    return f"  cycle: {joiner.join(cycle)}"


def render_summary(graph: LayerGraph) -> str:
    """A short human table of the graph's nodes, edges and findings."""
    lines = [
        f"{SCHEMA}  {graph.repo or graph.root}  {graph.commit or '(no commit)'}",
        f"declarations: {', '.join(graph.declarations)}",
        f"files {graph.stats.files}  imports {graph.stats.imports}  "
        f"unresolved {graph.stats.unresolved}",
        "",
        f"nodes ({len(graph.nodes)}):",
        *_table(
            [
                (n.id, f"{len(n.files)} files", ", ".join(n.runtimes))
                for n in graph.nodes
            ]
        ),
        "",
        f"edges ({len(graph.edges)}):",
        *_table(
            [
                (f"{e.source} -> {e.target}", str(e.imports), e.direction)
                for e in graph.edges
            ]
        ),
        "",
        "findings:",
        f"  outward: {len(graph.outward)}",
        *(f"  outward: {e.source} -> {e.target} ({e.imports})" for e in graph.outward),
        f"  cycles: {len(graph.cycles)}",
        *(_cycle_line(c) for c in graph.cycles),
        f"  unassigned: {len(graph.unassigned)}",
        *(f"  unassigned: {path}" for path in graph.unassigned),
    ]
    return "\n".join(lines) + "\n"
