"""Architect behavior: Purity (coding skill, Section 1.2).

The domain is the ubiquitous language of DYNOMARK.DESIGN.md ("Core: ...
None of these know a browser API, a wire format, a vendor, a model id, or a
database"). Mechanically: no module under ``domain/`` imports anything but
the standard library and ``domain/`` itself. Reading the package's own
source is the subject of this test, not incidental I/O.
"""

import ast
import sys
from pathlib import Path

import dynomark_daemon.domain as domain_package

DOMAIN = "dynomark_daemon.domain"
DOMAIN_DIR = Path(domain_package.__file__).parent


def _resolve(node: ast.ImportFrom, *, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _imported_modules(source: str, *, package: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(_resolve(node, package=package))
    return modules


def _is_allowed(module: str) -> bool:
    top = module.split(".")[0]
    in_domain = module == DOMAIN or module.startswith(DOMAIN + ".")
    return in_domain or top in sys.stdlib_module_names or top == "__future__"


def foreign_imports(source: str, *, package: str = DOMAIN) -> list[str]:
    """Every module ``source`` imports that is neither stdlib nor the domain."""
    return [m for m in _imported_modules(source, package=package) if not _is_allowed(m)]


def test_domain_modules_import_only_stdlib_and_domain() -> None:
    """Given every module under domain/, When its imports are walked, Then none
    leaves the stdlib or the domain (Core: no browser API, wire format,
    vendor, model id or database)."""
    sources = sorted(DOMAIN_DIR.rglob("*.py"))
    assert len(sources) > 1, "domain/ holds no modules; the guard would be vacuous"
    leaks = {
        str(path.relative_to(DOMAIN_DIR)): found
        for path in sources
        if (found := foreign_imports(path.read_text(encoding="utf-8")))
    }
    assert leaks == {}


def test_purity_check_flags_vendor_port_and_escaping_relative_imports() -> None:
    """Given a module importing pydantic, a port, or ``..wire`` relatively, When
    checked, Then each is reported (the guard can fail)."""
    source = (
        "import pydantic\n"
        "from dynomark_daemon.ports.store import CorpusStorePort\n"
        "from .. import wire\n"
    )
    assert foreign_imports(source) == [
        "pydantic",
        "dynomark_daemon.ports.store",
        "dynomark_daemon",
    ]


def test_purity_check_admits_stdlib_and_domain_imports() -> None:
    """Given a module importing only stdlib and domain modules, When checked,
    Then nothing is reported (the guard can pass)."""
    source = (
        "from __future__ import annotations\n"
        "import dataclasses\n"
        "from enum import StrEnum\n"
        "from dynomark_daemon.domain.ids import NodeId\n"
        "from .tree import FolderPath\n"
    )
    assert foreign_imports(source) == []
