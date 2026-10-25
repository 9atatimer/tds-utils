"""The Hexagonal quality's checks -- Grep, Arrow, Swap, Change -- driven
through `measure` with a fake behind every port (DESIGN.ARCH-ADHERENCE.md,
Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface)."""

from __future__ import annotations

from adherence.domain.finding import Finding
from adherence.domain.model import (
    Access,
    AccessKind,
    CodeModel,
    ImportEdge,
    Layer,
    Reference,
    ReferenceKind,
)
from adherence.domain.report import Report
from tests.measure_kit import measure_with

RULES = "src/app/domain/rules.py"
HTTP = "src/app/adapters/http.py"


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def test_measure_domain_naming_a_vendor_env_or_model_id_finds_a_leak() -> None:
    """Given a domain unit that imports a vendor, reads the environment and
    names a model id, When Grep runs, Then a finding names the unit, the
    symbol and the layer for each, and an adapter doing the same is clean."""
    files = {
        RULES: b'import requests\nimport app\nKEY = os.environ["K"]\nM = "claude-x"\n',
        HTTP: b'import requests\nM = "claude-x"\n',
    }
    facts = CodeModel(
        imports=(
            ImportEdge(RULES, "requests", 1, "import requests", None),
            ImportEdge(RULES, "app", 2, "import app", "src/app/__init__.py"),
            ImportEdge(HTTP, "requests", 1, "import requests", None),
        ),
        accesses=(Access(RULES, 3, None, AccessKind.ENVIRONMENT, "os.environ"),),
        references=(
            Reference(RULES, 4, None, ReferenceKind.STRING, "claude-x"),
            Reference(HTTP, 2, None, ReferenceKind.STRING, "claude-x"),
        ),
    )

    report = measure_with(files, facts)

    leaks = _of(report, "Grep")
    assert {(f.unit.path, f.subject, f.layer) for f in leaks} == {
        (RULES, "requests", Layer.DOMAIN),
        (RULES, "os.environ", Layer.DOMAIN),
        (RULES, "claude-x", Layer.DOMAIN),
    }
    assert all(f.check.quality.value == "Hexagonal" for f in leaks)


USE = "src/app/application/use.py"
STORE = "src/app/ports/store.py"
FS = "src/app/adapters/fs.py"
ROOT = "src/app/container.py"
TEST = "tests/test_use.py"
APP = (RULES, USE, STORE, FS, ROOT, TEST)


def _edge(path: str, imported: str, line: int = 1) -> ImportEdge:
    return ImportEdge(path, imported, line, f"import {imported}", imported)


def test_measure_whose_imports_all_cross_inward_has_no_arrow_finding() -> None:
    """Given a repository whose every import crosses inward, When Arrow runs,
    Then Arrow ran and there is no Arrow finding."""
    files = {path: b"import x\n" for path in APP}
    facts = CodeModel(
        imports=(
            _edge(USE, RULES),
            _edge(USE, STORE),
            _edge(STORE, RULES),
            _edge(FS, STORE),
            _edge(FS, RULES),
            _edge(ROOT, FS),
            _edge(ROOT, USE),
            _edge(TEST, USE),
            _edge(TEST, FS),
            ImportEdge(RULES, "dataclasses", 1, "import dataclasses", None),
        )
    )

    report = measure_with(files, facts)

    assert "Arrow" in {c.name for c in report.ran}
    assert _of(report, "Arrow") == []


def test_measure_with_an_outward_import_finds_the_arrow() -> None:
    """Given a domain unit that imports a port and a use case that imports an
    adapter, When Arrow runs, Then each is a finding naming the unit, its
    layer and the layer it reached."""
    files = {path: b"import x\n" for path in APP}
    facts = CodeModel(imports=(_edge(RULES, STORE), _edge(USE, FS)))

    report = measure_with(files, facts)

    assert {(f.unit.path, f.layer, f.reached) for f in _of(report, "Arrow")} == {
        (RULES, Layer.DOMAIN, Layer.PORTS),
        (USE, Layer.APPLICATION, Layer.ADAPTERS),
    }
