"""Architect behaviors (testing skill): Arrow, Grep and Purity as real tests.

Dependencies point inward (ARCHITECTURE.ARCH-ADHERENCE.md, Component
diagram): cli -> application -> domain; adapters -> ports -> domain. The
domain imports no port, adapter, subprocess, filesystem, environment or
vendor; the application imports no adapter; only the composition root
(container.py) names a concrete adapter, and it never imports the fakes.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "adherence"
LAYERS = ("domain", "ports", "application", "adapters", "cli")
LAYER_ALLOWED = {
    "domain": {"domain"},
    "ports": {"domain", "ports"},
    "application": {"domain", "ports", "application"},
    "adapters": {"domain", "ports", "adapters"},
    "cli": {"domain", "application", "cli", "container"},
}
# Modules that do I/O, read the environment or the clock: never in the core.
MECHANISM_MODULES = {
    "os",
    "subprocess",
    "pathlib",
    "shutil",
    "socket",
    "http",
    "urllib",
    "time",
    "datetime",
    "click",
}
CORE = ("domain", "application")


def _modules(layer: str) -> list[Path]:
    return sorted((SRC / layer).rglob("*.py"))


def _package(path: Path) -> list[str]:
    """The dotted package a module under SRC belongs to, as parts."""
    return ["adherence", *path.relative_to(SRC).parent.parts]


def _from_import(node: ast.ImportFrom, path: Path) -> list[str]:
    """The absolute modules a `from ... import` names, relative ones resolved."""
    if node.level == 0:
        return [node.module] if node.module else []
    package = _package(path)
    base = package[: len(package) - (node.level - 1)]
    if node.module:
        return [".".join([*base, node.module])]
    return [".".join([*base, alias.name]) for alias in node.names]


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.extend(_from_import(node, path))
    return names


def _target(name: str) -> str | None:
    """The engine layer an absolute import reaches, or None if outside it."""
    parts = name.split(".")
    if parts[0] != "adherence":
        return None
    return parts[1] if len(parts) > 1 else ""


def test_every_layer_is_a_package() -> None:
    """Given the engine, When its layers are listed, Then each is a package."""
    for layer in LAYERS:
        assert (SRC / layer / "__init__.py").is_file(), f"no {layer}/ package"
    assert (SRC / "container.py").is_file(), "no composition root"


def test_imports_point_inward() -> None:
    """Given any engine module, When its imports are read, Then each crosses inward."""
    for layer, allowed in LAYER_ALLOWED.items():
        for path in _modules(layer):
            for name in _imports(path):
                target = _target(name)
                assert target is None or target in allowed, (
                    f"{layer}/{path.name} imports {name}: the arrow points outward"
                )


def test_core_names_no_mechanism() -> None:
    """Given a domain or application module, When its imports are read,
    Then none is a mechanism (subprocess, fs, environment, clock, vendor)."""
    for layer in CORE:
        for path in _modules(layer):
            for name in _imports(path):
                top = name.split(".")[0]
                assert top not in MECHANISM_MODULES, (
                    f"{layer}/{path.name} imports {name}: a mechanism in the core"
                )


def test_only_the_composition_root_names_an_adapter() -> None:
    """Given the composition root, When its imports are read,
    Then it names adapters but never the fakes, and nothing else names one."""
    root = SRC / "container.py"
    assert "adherence.adapters.fakes" not in _imports(root), (
        "container.py imports the fakes; a test passes them in"
    )
    for layer in ("domain", "ports", "application", "cli"):
        for path in _modules(layer):
            for name in _imports(path):
                assert _target(name) != "adapters", (
                    f"{layer}/{path.name} imports {name}: only container.py may"
                )


def _module_name(path: Path) -> str:
    return ".".join(["adherence", *path.relative_to(SRC).with_suffix("").parts])


def _cycle_from(
    start: str, graph: dict[str, set[str]], path: tuple[str, ...]
) -> tuple[str, ...] | None:
    for name in sorted(graph.get(path[-1], ())):
        if name == start:
            return (*path, start)
        if name not in path:
            found = _cycle_from(start, graph, (*path, name))
            if found is not None:
                return found
    return None


def test_the_domain_imports_form_no_cycle() -> None:
    """Given the domain's modules, When their imports are read, a
    TYPE_CHECKING import among them, Then no module reaches itself."""
    modules = {_module_name(p): p for p in _modules("domain")}
    graph = {
        name: {i for i in _imports(path) if i in modules and i != name}
        for name, path in modules.items()
    }
    for name in sorted(graph):
        cycle = _cycle_from(name, graph, (name,))
        assert cycle is None, " -> ".join(cycle or ())


def _nested(tree: ast.AST) -> list[str]:
    """The functions defined inside a function, by name."""
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    return [
        inner.name
        for outer in ast.walk(tree)
        if isinstance(outer, functions)
        for inner in ast.walk(outer)
        if inner is not outer and isinstance(inner, functions)
    ]


def test_no_engine_function_is_nested_in_another() -> None:
    """Given any engine module, When its definitions are read, Then no
    function is defined inside another: each is a unit a test can reach."""
    for path in sorted(SRC.rglob("*.py")):
        nested = _nested(ast.parse(path.read_text()))
        assert nested == [], f"{path.relative_to(SRC)} nests {nested}"
