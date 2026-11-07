"""Barrel transparency: an import landing on a re-export-only file reaches
the files it re-exports."""

from layer_graph.domain.barrels import Surface, declaring_files, through_barrels


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


def _surfaces() -> dict[str, Surface]:
    return {
        "index.ts": Surface(
            local=frozenset(),
            named=(("ns", "*", "ns.ts"), ("W", "default", "w.ts")),
            stars=("a.ts", "nested.ts"),
        ),
        "nested.ts": Surface(local=frozenset(), named=(), stars=("deep.ts",)),
        "a.ts": Surface(local=frozenset({"alpha"}), named=(), stars=()),
        "deep.ts": Surface(local=frozenset({"deep"}), named=(), stars=()),
        "ns.ts": Surface(local=frozenset({"n"}), named=(), stars=()),
        "w.ts": Surface(local=frozenset({"default"}), named=(), stars=()),
    }


BARRELS = {
    "index.ts": ("ns.ts", "w.ts", "a.ts", "nested.ts"),
    "nested.ts": ("deep.ts",),
}


def test_declaring_files_follows_star_to_the_declaring_file() -> None:
    """Given a name a star re-export provides, When resolved through the
    barrel, Then only the file declaring it is reached."""
    assert declaring_files("index.ts", "alpha", _surfaces(), BARRELS) == ("a.ts",)


def test_declaring_files_follows_nested_barrels() -> None:
    """Given a name declared behind a nested barrel, When resolved, Then the
    deep file is reached."""
    assert declaring_files("index.ts", "deep", _surfaces(), BARRELS) == ("deep.ts",)


def test_declaring_files_namespace_reexport_binds_the_whole_file() -> None:
    """Given export * as ns, When ns is imported, Then the namespaced file is
    reached."""
    assert declaring_files("index.ts", "ns", _surfaces(), BARRELS) == ("ns.ts",)


def test_declaring_files_named_default_reexport_reaches_its_file() -> None:
    """Given export { default as W }, When W is imported, Then the file whose
    default it is is reached."""
    assert declaring_files("index.ts", "W", _surfaces(), BARRELS) == ("w.ts",)


def test_declaring_files_unknown_name_or_default_is_none() -> None:
    """Given a name no re-export provides, or default (which export * never
    carries), When resolved, Then nothing is claimed."""
    assert declaring_files("index.ts", "nope", _surfaces(), BARRELS) is None
    assert declaring_files("index.ts", "default", _surfaces(), BARRELS) is None


def test_declaring_files_survives_a_star_cycle() -> None:
    """Given two barrels starring each other, When an absent name is resolved,
    Then it ends with nothing claimed."""
    surfaces = {
        "x.ts": Surface(local=frozenset(), named=(), stars=("y.ts",)),
        "y.ts": Surface(local=frozenset(), named=(), stars=("x.ts",)),
    }
    barrels = {"x.ts": ("y.ts",), "y.ts": ("x.ts",)}
    assert declaring_files("x.ts", "a", surfaces, barrels) is None
