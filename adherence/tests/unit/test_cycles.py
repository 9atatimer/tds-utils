"""Arrow's cycle search as pure functions over a graph, property-tested."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from adherence.domain.checks.hexagonal import cycle_through, strongly_connected

NODES = st.sampled_from([f"m{i}.py" for i in range(8)])
GRAPHS = st.dictionaries(NODES, st.lists(NODES, unique=True).map(sorted))


@given(GRAPHS)
def test_strongly_connected_partitions_every_node_into_one_component(
    graph: dict[str, list[str]],
) -> None:
    """Given any graph, When its components are found, Then every node that
    has arcs is in exactly one component."""
    components = strongly_connected(graph)

    members = [node for component in components for node in component]
    assert len(members) == len(set(members))
    assert set(graph) <= set(members)


@given(GRAPHS)
def test_cycle_through_a_component_is_a_closed_walk_of_its_arcs(
    graph: dict[str, list[str]],
) -> None:
    """Given any graph, When a cycle is traced through each component of two
    or more nodes, Then it starts and ends at its first member and each step
    is an arc of the graph inside the component."""
    for component in strongly_connected(graph):
        if len(component) < 2:
            continue
        path = cycle_through(component[0], component, graph)

        assert path[0] == path[-1] == component[0]
        assert len(path) >= 3
        for here, there in zip(path, path[1:], strict=False):
            assert there in graph.get(here, [])
            assert there in component
