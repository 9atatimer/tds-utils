"""Architect behaviors (coding skill, Section 1.2): Arrow and Trace.

Arrow: the application layer imports only the standard library, the domain,
the ports and itself -- never an adapter, the wire format or a vendor.
Trace: every daemon use case the design's Behaviors and Interfaces table
names (PoC and MVP) resolves to one application function, whose ports are
keyword-only dependencies after its values. Reading the package's own
source is the subject of these tests, not incidental I/O.
"""

import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest

import dynomark_daemon.app as app_package

APP_DIR = Path(app_package.__file__).parent
APP_PACKAGE = "dynomark_daemon.app"
ALLOWED = ("dynomark_daemon.domain", "dynomark_daemon.ports", "dynomark_daemon.app")
PORT_PARAMETERS = {
    "store",
    "embedding",
    "completion",
    "content",
    "transport",
    "clock",
    "ids",
}
POC_USE_CASES = {
    "ingest": "ingest",
    "capture": "capture",
    "process_job": "process",
    "place": "place",
    "file": "file",
    "undo": "undo",
    "receive_receipt": "receipt",
    "search_corpus": "search",
    "build_local_index": "index",
}
MVP_USE_CASES = {
    "ask": "ask",
    "propose_diff": "diffs",
    "accept_diff_item": "diffs",
    "explain_placement": "explain",
}
PORTLESS = {"accept_diff_item"}
"""Use cases the design's table lists with no port ("none")."""


def _imports(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append(node.module)
    return found


def _is_allowed(module: str) -> bool:
    top = module.split(".")[0]
    inward = any(module == a or module.startswith(a + ".") for a in ALLOWED)
    return inward or top in sys.stdlib_module_names


def test_application_imports_only_stdlib_domain_ports_and_itself() -> None:
    """Given every module under app/, When its imports are walked, Then each
    points inward: no adapter, wire model, vendor SDK or database."""
    sources = sorted(APP_DIR.rglob("*.py"))
    assert len(sources) > 5
    leaks = {
        path.name: bad
        for path in sources
        if (
            bad := [
                m
                for m in _imports(path.read_text("utf-8"), package=APP_PACKAGE)
                if not _is_allowed(m)
            ]
        )
    }
    assert leaks == {}


def test_the_arrow_guard_reports_relative_imports_of_adapters_and_wire() -> None:
    """Given an app module importing an adapter and the wire format by
    relative imports, When the guard walks it, Then both are reported -- the
    guard can fail -- while relative imports of the domain, the ports and
    app itself pass."""
    source = (
        "from ..adapters.sqlite_store import SqliteCorpusStore\n"
        "from ..wire import codec\n"
        "from ..domain.job import Job\n"
        "from ..ports.store import CorpusStorePort\n"
        "from .errors import Busy\n"
        "from . import loop\n"
    )

    imported = _imports(source, package="dynomark_daemon.app")

    leaks = [module for module in imported if not _is_allowed(module)]
    assert leaks == ["dynomark_daemon.adapters.sqlite_store", "dynomark_daemon.wire"]


@pytest.mark.parametrize(
    ("name", "module"), sorted({**POC_USE_CASES, **MVP_USE_CASES}.items())
)
def test_each_use_case_is_one_app_function_with_keyword_only_ports(
    name: str, module: str
) -> None:
    """Given a daemon use case of the design's Behaviors table, When its
    application module is loaded, Then the function exists and every port it
    takes is keyword-only, after the values."""
    function = getattr(importlib.import_module(f"dynomark_daemon.app.{module}"), name)
    parameters = inspect.signature(function).parameters.values()

    ports = [p for p in parameters if p.name in PORT_PARAMETERS]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in ports)
    assert ports or name in PORTLESS, f"{name} takes no port"
