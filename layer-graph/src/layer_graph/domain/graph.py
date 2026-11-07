"""The node graph: edge direction by layer depth, and cycles between nodes.

Layer order, outermost to innermost: composition root, adapters,
application, ports, domain; the test layer sits outside all of them. An edge
into a deeper layer is inward, one within a layer is lateral, one into a
shallower layer is outward -- a violation of the dependency rule.
"""

from collections import defaultdict
from collections.abc import Iterable

from layer_graph.domain.declaration import layer_depth

# --- Constants ---------------------------------------------------------------

INWARD = "inward"
LATERAL = "lateral"
OUTWARD = "outward"


# --- Predicates --------------------------------------------------------------


def is_outward(direction_name: str) -> bool:
    """Whether a direction breaks the dependency rule."""
    return direction_name == OUTWARD


# --- Pure helpers ------------------------------------------------------------


def direction(source_layer: str, target_layer: str) -> str:
    """The direction of an edge from a node in one layer to a node in another."""
    source, target = layer_depth(source_layer), layer_depth(target_layer)
    if target > source:
        return INWARD
    if target == source:
        return LATERAL
    return OUTWARD


def _components(adjacency: dict[str, list[str]]) -> list[list[str]]:
    """Strongly connected components (Tarjan's algorithm, iterative)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    found: list[list[str]] = []
    counter = 0
    for start in sorted(adjacency):
        if start in index:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            neighbours = adjacency.get(node, [])
            if child < len(neighbours):
                work.append((node, child + 1))
                successor = neighbours[child]
                if successor not in index:
                    work.append((successor, 0))
                elif successor in on_stack:
                    low[node] = min(low[node], index[successor])
                continue
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                found.append(sorted(component))
    return found


def cycles(edges: Iterable[tuple[str, str]]) -> list[list[str]]:
    """Every strongly connected component of more than one node, then every
    mutually importing pair not already reported as its own component;
    each sorted: components first, then pairs."""
    pairs = {(s, t) for s, t in edges if s != t}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, target in sorted(pairs):
        adjacency[source].append(target)
        adjacency.setdefault(target, [])
    components = [c for c in _components(adjacency) if len(c) > 1]
    mutual = sorted([s, t] for s, t in pairs if s < t and (t, s) in pairs)
    return sorted(components) + [m for m in mutual if m not in components]
