"""Architect behaviors (testing skill): the Grep and Arrow tests as real tests.

domain/ names no vendor, SDK, environment, filesystem, subprocess or model id;
imports point inward: domain -> stdlib only; ports -> domain; application ->
ports + domain; adapters -> ports + domain; cli -> anything.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "chores"
FORBIDDEN_MODULES = {
    "os",
    "subprocess",
    "urllib",
    "http",
    "socket",
    "yaml",
    "click",
    "structlog",
    "textual",
    "rumps",
    "json",
    "pathlib",
    "shutil",
}
VENDOR_WORDS = (
    "claude",
    "ollama",
    "openai",
    "cloudflare",
    "anthropic",
    "launchd",
    "systemd",
    "pmset",
    "osascript",
    "/users/",
    ".config/",
    "op://",
)
LAYER_ALLOWED = {
    "domain": set(),
    "ports": {"domain"},
    "application": {"domain", "ports"},
    "adapters": {"domain", "ports"},
}


def _modules(layer: str) -> list[Path]:
    return sorted((SRC / layer).rglob("*.py"))


def _imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _code_strings(tree: ast.Module) -> list[str]:
    """String constants that are code, not docstrings."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
            ):
                docstrings.add(id(body[0].value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
    ]


def test_domain_imports_nothing_concrete() -> None:
    """Grep test: no os/subprocess/http/yaml/... in the core."""
    for path in _modules("domain"):
        tree = ast.parse(path.read_text())
        for name in _imports(tree):
            top = name.split(".")[0]
            assert top not in FORBIDDEN_MODULES, f"{path.name} imports {name}"
            assert not name.startswith("chores.") or name.startswith("chores.domain"), (
                f"{path.name} imports outward: {name}"
            )


def test_domain_code_names_no_vendor_or_host_detail() -> None:
    """Grep test: no vendor, host path, or model id in domain string literals."""
    for path in _modules("domain"):
        for literal in _code_strings(ast.parse(path.read_text())):
            low = literal.lower()
            for word in VENDOR_WORDS:
                assert word not in low, f"{path.name} mentions {word!r} in {literal!r}"


def test_imports_point_inward() -> None:
    """Arrow test: each layer imports only the layers inside it."""
    for layer, allowed in LAYER_ALLOWED.items():
        for path in _modules(layer):
            for name in _imports(ast.parse(path.read_text())):
                if not name.startswith("chores."):
                    continue
                parts = name.split(".")
                target = parts[1] if len(parts) > 1 else ""
                assert target in allowed | {layer}, (
                    f"{layer}/{path.name} imports {name}"
                )
