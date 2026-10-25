"""measure, the report-level rows (DESIGN.ARCH-ADHERENCE.md, Behaviors;
ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface), driven by its signature
with a fake behind every port."""

from __future__ import annotations

from adherence.domain.declaration import DeclarationUnreadable
from adherence.domain.model import CodeModel, ImportEdge
from tests.measure_kit import measure_with

RULES = "src/app/domain/rules.py"


def test_measure_with_an_unreadable_declaration_is_not_run() -> None:
    """Given a declaration in force that cannot be read, When a run is asked
    for, Then the report is not run, names the error, and holds no finding."""
    files = {RULES: b"import requests\n"}
    facts = CodeModel(
        imports=(ImportEdge(RULES, "requests", 1, "import requests", None),)
    )

    report = measure_with(
        files, facts, DeclarationUnreadable("adherence.toml: line 3, bad key")
    )

    assert report.not_run_reason is not None
    assert "adherence.toml: line 3, bad key" in report.not_run_reason
    assert report.findings == ()
