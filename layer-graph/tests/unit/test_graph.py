"""Edge direction and cycle detection over the node graph."""

from layer_graph.domain.graph import cycles, direction


def test_direction_to_deeper_layer_is_inward() -> None:
    """Given an application node importing a domain node, When classified,
    Then the edge is inward."""
    assert direction("application", "domain") == "inward"
    assert direction("composition root", "adapters") == "inward"
    assert direction("adapters", "ports") == "inward"


def test_direction_within_one_layer_is_lateral() -> None:
    """Given two contexts in one layer, When classified, Then the edge is
    lateral."""
    assert direction("domain", "domain") == "lateral"


def test_direction_to_shallower_layer_is_outward() -> None:
    """Given a domain node importing an application node, When classified,
    Then the edge is outward."""
    assert direction("domain", "application") == "outward"
    assert direction("adapters", "composition root") == "outward"


def test_direction_test_layer_sits_outside_every_layer() -> None:
    """Given the test layer, When classified, Then a test importing code is
    inward and code importing a test is outward."""
    assert direction("test", "composition root") == "inward"
    assert direction("domain", "test") == "outward"


def test_cycles_reports_mutual_pair() -> None:
    """Given two nodes importing each other, When cycles are found, Then the
    pair is reported once."""
    edges = [
        ("domain/table", "domain/timeline"),
        ("domain/timeline", "domain/table"),
        ("domain/table", "domain/kernel"),
    ]
    assert cycles(edges) == [["domain/table", "domain/timeline"]]


def test_cycles_reports_component_and_its_mutual_pairs() -> None:
    """Given a three-node loop with one mutual pair inside it, When cycles are
    found, Then the component and the pair are both reported."""
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("c", "b")]
    assert cycles(edges) == [["a", "b", "c"], ["b", "c"]]


def test_cycles_acyclic_graph_has_none() -> None:
    """Given a graph with no loop, When cycles are found, Then none is
    reported."""
    assert cycles([("a", "b"), ("b", "c"), ("a", "c")]) == []
