"""Barrel transparency: an import landing on a re-export-only file reaches
the files it re-exports."""

from layer_graph.domain.barrels import through_barrels


def test_through_barrels_leaves_ordinary_targets_alone() -> None:
    """Given a target that is not a barrel, When redirected, Then it stays and
    no barrel was crossed."""
    assert through_barrels(("a.ts",), {}) == (("a.ts",), False)


def test_through_barrels_follows_nested_barrels() -> None:
    """Given a barrel re-exporting a file and another barrel, When an import
    lands on it, Then it reaches every non-barrel file transitively."""
    barrels = {"index.ts": ("a.ts", "sub/index.ts"), "sub/index.ts": ("b.ts",)}
    assert through_barrels(("index.ts",), barrels) == (("a.ts", "b.ts"), True)


def test_through_barrels_survives_a_barrel_cycle() -> None:
    """Given two barrels re-exporting each other, When an import lands on one,
    Then redirection ends and reaches the real file once."""
    barrels = {"x.ts": ("y.ts", "a.ts"), "y.ts": ("x.ts", "a.ts")}
    assert through_barrels(("x.ts",), barrels) == (("a.ts",), True)
