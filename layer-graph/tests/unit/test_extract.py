"""The use case: a repository's declarations and sources in, its graph out.

Driven against tiny fixture repositories copied into a temporary root and
read through the disk adapter.
"""

from pathlib import Path

import pytest

from layer_graph.adapters.disk import DiskRepository
from layer_graph.application.extract import (
    DeclarationUnreadable,
    NoDeclaration,
    extract,
)
from layer_graph.domain.report import LayerGraph
from tests.fixture_repo import copy_fixture


def _graph(
    tmp_path: Path, name: str, *, include_tests: bool = False, barrels: bool = False
) -> LayerGraph:
    """The fixture's graph; barrels off unless asked, so the resolution tests
    see the file each specifier names."""
    root = copy_fixture(name, tmp_path)
    return extract(
        source=DiskRepository(root), include_tests=include_tests, barrels=barrels
    )


def _edges(graph: LayerGraph) -> dict[tuple[str, str], tuple[int, str]]:
    return {(e.source, e.target): (e.imports, e.direction) for e in graph.edges}


def _node_ids(graph: LayerGraph) -> set[str]:
    return {n.id for n in graph.nodes}


# --- TypeScript monorepo ---------------------------------------------------


def test_extract_ts_nodes_follow_layer_and_context(tmp_path: Path) -> None:
    """Given a declared TypeScript monorepo, When extracted, Then each unit
    lands in the node its layer and context name, colliding names qualified."""
    graph = _graph(tmp_path, "ts_mono")
    assert _node_ids(graph) == {
        "domain/timeline",
        "domain/table",
        "domain/kernel",
        "application/table",
        "ports/ports",
        "adapters/adapters-memory",
        "adapters/components",
        "adapters/composables",
        "composition root/core:index",
        "composition root/assistant:index",
        "composition root/server:composition",
        "composition root/app:composition",
    }
    kernel = next(n for n in graph.nodes if n.id == "domain/kernel")
    assert kernel.files == (
        "packages/core/src/domain/kernel/ids.ts",
        "packages/core/src/domain/kernel/index.ts",
    )


def test_extract_ts_relative_imports_resolve_with_probing(tmp_path: Path) -> None:
    """Given relative imports with no extension, a .js extension for a .ts
    file, and a directory index, When extracted, Then each reaches its file."""
    edges = _edges(_graph(tmp_path, "ts_mono"))
    assert edges[("domain/timeline", "domain/table")] == (1, "lateral")
    assert edges[("domain/table", "domain/timeline")] == (1, "lateral")
    assert edges[("ports/ports", "domain/kernel")] == (1, "inward")
    assert edges[("application/table", "domain/kernel")] == (1, "inward")
    assert edges[("application/table", "ports/ports")] == (1, "inward")


def test_extract_ts_workspace_packages_resolve(tmp_path: Path) -> None:
    """Given imports of workspace packages by name, by exports pattern, by a
    conditional export, and by main, When extracted, Then each reaches the
    package's file."""
    edges = _edges(_graph(tmp_path, "ts_mono"))
    assert edges[("adapters/adapters-memory", "composition root/core:index")] == (
        1,
        "outward",
    )
    assert edges[("adapters/adapters-memory", "domain/kernel")] == (1, "inward")
    assert edges[("adapters/adapters-memory", "ports/ports")] == (1, "inward")
    assert edges[("composition root/app:composition", "adapters/adapters-memory")] == (
        1,
        "inward",
    )
    assert edges[
        ("composition root/assistant:index", "composition root/core:index")
    ] == (1, "lateral")


def test_extract_ts_vue_script_and_tsconfig_paths_resolve(tmp_path: Path) -> None:
    """Given a .vue file importing through a tsconfig paths alias that a
    referenced tsconfig declares, When extracted, Then only its script imports
    count and the alias resolves."""
    edges = _edges(_graph(tmp_path, "ts_mono"))
    assert edges[("adapters/components", "adapters/composables")] == (1, "lateral")
    assert edges[("adapters/components", "composition root/core:index")] == (
        1,
        "outward",
    )


def test_extract_ts_counts_files_imports_and_unresolved(tmp_path: Path) -> None:
    """Given the monorepo, When extracted, Then the stats count unit files,
    every import statement in them, and the one external specifier."""
    graph = _graph(tmp_path, "ts_mono")
    assert (graph.stats.files, graph.stats.imports, graph.stats.unresolved) == (
        14,
        20,
        1,
    )


def test_extract_ts_findings_outward_cycles_unassigned(tmp_path: Path) -> None:
    """Given a domain file importing the application and two domain contexts
    importing each other, When extracted, Then the outward edges, the cycle and
    the undeclared script are findings."""
    graph = _graph(tmp_path, "ts_mono")
    outward = {(e.source, e.target) for e in graph.outward}
    assert outward == {
        ("domain/table", "application/table"),
        ("adapters/adapters-memory", "composition root/core:index"),
        ("adapters/components", "composition root/core:index"),
    }
    assert graph.cycles == (("domain/table", "domain/timeline"),)
    assert graph.unassigned == ("scripts/tool.ts",)


def test_extract_ts_runtimes_name_their_nodes(tmp_path: Path) -> None:
    """Given declared runtimes, When extracted, Then each lists the nodes with
    a file under its patterns, and each node lists its runtimes."""
    graph = _graph(tmp_path, "ts_mono")
    assert graph.runtimes["assistant worker"] == ("composition root/assistant:index",)
    assert set(graph.runtimes["browser"]) == {
        "adapters/components",
        "adapters/composables",
        "composition root/app:composition",
    }
    timeline = next(n for n in graph.nodes if n.id == "domain/timeline")
    assert timeline.runtimes == ("app worker",)


def test_extract_ts_tests_excluded_unless_asked(tmp_path: Path) -> None:
    """Given a declared test layer, When extracted without and then with
    tests, Then the test node appears only when asked and points inward."""
    assert "test/core" not in _node_ids(_graph(tmp_path / "a", "ts_mono"))
    graph = _graph(tmp_path / "b", "ts_mono", include_tests=True)
    assert _edges(graph)[("test/core", "domain/timeline")] == (1, "inward")


def test_extract_skips_build_and_dependency_directories(tmp_path: Path) -> None:
    """Given declared sources inside node_modules and dist, When extracted,
    Then neither becomes a unit or an unassigned file."""
    root = copy_fixture("ts_mono", tmp_path)
    for skipped in ("node_modules/x", "dist", ".output", "build", "__pycache__"):
        directory = root / "packages/core/src/domain/kernel" / skipped
        directory.mkdir(parents=True)
        (directory / "index.ts").write_text("export const x = 1;\n")
    graph = extract(source=DiskRepository(root), include_tests=False, barrels=False)
    assert graph.stats.files == 14


# --- Python ----------------------------------------------------------------


def test_extract_python_resolves_absolute_relative_and_src_layout(
    tmp_path: Path,
) -> None:
    """Given a src-layout Python package, When extracted, Then absolute,
    from-import and relative imports resolve and stdlib or third-party ones
    are unresolved."""
    graph = _graph(tmp_path, "py_repo")
    edges = _edges(graph)
    assert edges == {
        ("application/application", "domain/domain"): (2, "inward"),
        ("adapters/adapters", "application/application"): (1, "inward"),
        ("composition root/cli", "adapters/adapters"): (1, "inward"),
    }
    assert (graph.stats.files, graph.stats.imports, graph.stats.unresolved) == (
        8,
        7,
        2,
    )
    assert graph.unassigned == ("src/app/__init__.py",)


def test_extract_python_test_layer_included_on_request(tmp_path: Path) -> None:
    """Given a Python test importing a domain module, When extracted with
    tests, Then the test node points inward at it."""
    graph = _graph(tmp_path, "py_repo", include_tests=True)
    assert _edges(graph)[("test/tests", "domain/domain")] == (1, "inward")


# --- Declarations ----------------------------------------------------------


def test_extract_merges_nested_declarations_by_subtree(tmp_path: Path) -> None:
    """Given a root declaration and one in a sub-project, When extracted, Then
    both declare layers and runtimes for their own subtree, a declaration the
    root assigns to the test layer is test data, and an override replaces the
    layers for its subtree."""
    graph = _graph(tmp_path, "nested")
    assert graph.declarations == (
        "adherence.toml",
        "override/adherence.toml",
        "sub/adherence.toml",
    )
    assert _node_ids(graph) == {"domain/core", "adapters/edge", "application/override"}
    assert _edges(graph) == {("adapters/edge", "domain/core"): (1, "inward")}
    assert graph.runtimes == {"lib": ("domain/core",), "service": ("adapters/edge",)}
    assert graph.unassigned == ("sub/loose.py",)


def test_extract_without_declaration_raises_no_declaration(tmp_path: Path) -> None:
    """Given a repository with no adherence.toml, When extracted, Then it says
    there is no declaration."""
    with pytest.raises(NoDeclaration):
        _graph(tmp_path, "no_decl")


def test_extract_unreadable_declaration_raises_with_its_path(tmp_path: Path) -> None:
    """Given a declaration that is not valid TOML, When extracted, Then the
    error names the file."""
    with pytest.raises(DeclarationUnreadable, match="adherence.toml"):
        _graph(tmp_path, "bad_decl")


def test_extract_unknown_layer_is_unreadable(tmp_path: Path) -> None:
    """Given a declaration naming a layer the suite does not know, When
    extracted, Then it is unreadable."""
    (tmp_path / "adherence.toml").write_text('[layers]\nservices = ["src/**"]\n')
    with pytest.raises(DeclarationUnreadable, match="services"):
        extract(source=DiskRepository(tmp_path), include_tests=False, barrels=False)


# --- Barrels ---------------------------------------------------------------


def test_extract_barrels_redirect_imports_to_reexported_files(
    tmp_path: Path,
) -> None:
    """Given re-export-only index files, When extracted with barrels on, Then
    imports landing on them reach the files they re-export, one edge per
    reached node, and the barrels are no longer nodes."""
    graph = _graph(tmp_path, "ts_mono", barrels=True)
    edges = _edges(graph)
    assert "composition root/core:index" not in _node_ids(graph)
    assert "composition root/index" in _node_ids(graph)
    assert edges[("adapters/adapters-memory", "domain/timeline")] == (1, "inward")
    assert ("adapters/adapters-memory", "application/table") not in edges
    assert edges[("adapters/adapters-memory", "domain/kernel")] == (1, "inward")
    assert edges[("adapters/components", "domain/timeline")] == (1, "inward")
    assert edges[("composition root/index", "application/table")] == (1, "inward")
    assert edges[("composition root/index", "domain/timeline")] == (1, "inward")
    assert edges[("ports/ports", "domain/kernel")] == (1, "inward")
    kernel = next(n for n in graph.nodes if n.id == "domain/kernel")
    assert kernel.files == ("packages/core/src/domain/kernel/ids.ts",)


def test_extract_barrels_leave_only_real_outward_edges(tmp_path: Path) -> None:
    """Given adapters that import the core through its barrel, When extracted
    with barrels on, Then only the domain file importing the application is
    outward."""
    graph = _graph(tmp_path, "ts_mono", barrels=True)
    assert {(e.source, e.target) for e in graph.outward} == {
        ("domain/table", "application/table"),
    }


def test_extract_barrels_count_redirected_imports(tmp_path: Path) -> None:
    """Given six import statements that land on a barrel, When extracted with
    barrels on, Then stats count them as via a barrel, and the barrels' own
    re-exports are not unit imports."""
    stats = _graph(tmp_path, "ts_mono", barrels=True).stats
    assert (stats.files, stats.imports, stats.unresolved, stats.via_barrel) == (
        12,
        17,
        1,
        6,
    )
    assert stats.barrel_fallback == 1


def test_extract_without_barrels_counts_none_via_barrel(tmp_path: Path) -> None:
    """Given barrels off, When extracted, Then no import is redirected."""
    assert _graph(tmp_path, "ts_mono").stats.via_barrel == 0


def test_extract_barrels_resolve_named_imports_by_symbol(tmp_path: Path) -> None:
    """Given named, aliased, type, default-alias, namespace, nested and
    re-exported imports through a package barrel, When extracted, Then each
    statement reaches only the node that declares what it names."""
    edges = _edges(_graph(tmp_path, "ts_barrels", barrels=True))
    by_source: dict[str, set[str]] = {}
    for source, target in edges:
        by_source.setdefault(source, set()).add(target)
    assert by_source["adapters/named"] == {"domain/alpha"}
    assert by_source["adapters/locals"] == {"domain/alpha"}
    assert by_source["adapters/reexp"] == {"domain/alpha"}
    assert by_source["adapters/nsuse"] == {"domain/space"}
    assert by_source["adapters/def"] == {"domain/widget"}
    assert by_source["adapters/deepuse"] == {"domain/deep"}
    assert edges[("adapters/named", "domain/alpha")] == (1, "inward")


def test_extract_barrels_fall_back_to_fan_out_and_count_it(tmp_path: Path) -> None:
    """Given a namespace import, a name the barrel lacks and a default import
    the barrel never re-exports, When extracted, Then each fans out to every
    node behind the barrel and counts as a fallback."""
    graph = _graph(tmp_path, "ts_barrels", barrels=True)
    edges = _edges(graph)
    everything = {"domain/alpha", "domain/space", "domain/widget", "domain/deep"}
    for source in ("adapters/star", "adapters/missing", "adapters/defbarrel"):
        assert {t for s, t in edges if s == source} == everything
    assert (graph.stats.via_barrel, graph.stats.barrel_fallback) == (9, 3)
