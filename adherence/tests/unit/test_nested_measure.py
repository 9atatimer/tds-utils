"""measure under nested declarations: a path no declaration governs is an
undeclared subtree, and the record-reading checks read each subtree's own
records (DESIGN.ARCH-ADHERENCE.md, Behaviors, An undeclared subtree has no
adherence and Governing declarations are read as one)."""

from __future__ import annotations

from collections.abc import Mapping

from adherence.adapters.fakes import (
    FakeCodeModel,
    FakeComplexity,
    FakeDecision,
    FakeDuplication,
    FakeRecords,
    FakeRepository,
)
from adherence.application.measure import measure
from adherence.domain.coverage import UNDECLARED_SUBTREE
from adherence.domain.declaration import (
    Declaration,
    governing_declarations,
    parse_file,
)
from adherence.domain.model import (
    Body,
    CodeLanguage,
    CodeModel,
    Definition,
    Parameter,
    Signature,
    Unit,
    UnitKind,
)
from adherence.domain.questions import Unavailable
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    SurfaceRow,
    UseCase,
)
from adherence.domain.report import Report
from adherence.domain.target import Head
from tests.measure_kit import parameters

HEAD = Head.working_tree()
SUB = b"""
[layers]
application = ["src/application/**"]
domain = ["src/domain/**"]

[records]
design = "DESIGN.md"
architecture = "ARCHITECTURE.md"
"""
CLOSED = "An order is closed"
SCENARIO = "Given an open order, When it is closed, Then the store holds it closed"


def _declaration(files: Mapping[str, bytes]) -> Declaration:
    parsed = [parse_file(path, text) for path, text in files.items()]
    assert all(isinstance(p, Declaration) for p in parsed), parsed
    merged = governing_declarations(
        [p for p in parsed if isinstance(p, Declaration)], ()
    )
    assert isinstance(merged, Declaration), merged
    return merged


def _measured(
    files: Mapping[str, bytes],
    declaration: Declaration,
    facts: CodeModel | None = None,
    records: FakeRecords | None = None,
) -> Report:
    return measure(
        HEAD,
        declaration,
        repository=FakeRepository({HEAD: files}),
        analyzers={CodeLanguage.PYTHON: FakeCodeModel(facts=facts or CodeModel())},
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=records or FakeRecords({}),
        judge=FakeDecision(Unavailable("no judge in the unit tier")),
        parameters=parameters(),
        deadline=None,
    )


def test_an_undeclared_subtree_is_coverage_and_never_modelled() -> None:
    """Given a declaration in pkg-a only, When the repository is measured,
    Then no unit under pkg-c is modelled, and each of pkg-c's paths is one
    coverage line saying no declaration governs it."""
    files = {
        "pkg-a/adherence.toml": SUB,
        "pkg-a/src/domain/rules.py": b"x = 1\n",
        "pkg-c/tool.py": b"x = 1\n",
        "pkg-c/notes.md": b"notes\n",
    }

    report = _measured(files, _declaration({"pkg-a/adherence.toml": SUB}))

    assert {u.path for u in report.units} == {"pkg-a/src/domain/rules.py"}
    undeclared = sorted(
        c.path or "" for c in report.coverage if c.reason == UNDECLARED_SUBTREE
    )
    assert undeclared == ["pkg-c/notes.md", "pkg-c/tool.py"]


def test_a_declared_subtree_path_in_no_layer_is_still_unassigned() -> None:
    """Given a file under a governing declaration that no layer covers,
    When the repository is measured, Then it is modelled and is coverage as
    in no declared layer, not as an undeclared subtree."""
    files = {"pkg-a/adherence.toml": SUB, "pkg-a/scripts/run.py": b"x = 1\n"}

    report = _measured(files, _declaration({"pkg-a/adherence.toml": SUB}))

    assert "pkg-a/scripts/run.py" in {u.path for u in report.units}
    reasons = {c.reason for c in report.coverage if c.path == "pkg-a/scripts/run.py"}
    assert UNDECLARED_SUBTREE not in reasons
    assert any("no declared layer" in r for r in reasons), reasons


def _function(path: str, symbol: str) -> Definition:
    unit = Unit(path, UnitKind.FUNCTION, symbol, 1, 2, None)
    return Definition(
        unit=unit,
        signature=Signature((Parameter("order", None, False, False),), None),
        body=Body("return order", (), ()),
        bases=(),
        decorators=(),
        parent=None,
        nested=False,
    )


def _carrying(design: str, architecture: str) -> DesignRecords:
    return DesignRecords(
        behaviors=(Behavior(CLOSED, SCENARIO, design, 9),),
        use_cases=(
            UseCase(
                "close_order",
                Signature((Parameter("order", None, False, False),), "str"),
                architecture,
                12,
            ),
        ),
        surface=(SurfaceRow(CLOSED, "close_order", architecture, 12),),
    )


def test_a_behavior_is_traced_only_against_its_own_sub_projects_units() -> None:
    """Given sub-projects a and b, each naming its own design record, a's
    stating a behavior whose use case only b's code carries, When the
    repository is measured, Then Trace finds a's behavior homeless (b's
    unit is not a's) and reports b's record, which states no behavior, as
    coverage for b alone."""
    files = {
        "a/adherence.toml": SUB,
        "b/adherence.toml": SUB,
        "a/src/domain/rules.py": b"x = 1\n",
        "b/src/application/use.py": b"def close_order(order): ...\n",
    }
    facts = CodeModel(
        definitions=(_function("b/src/application/use.py", "close_order"),)
    )
    records = FakeRecords(
        {},
        by_record={
            "a/DESIGN.md": _carrying("a/DESIGN.md", "a/ARCHITECTURE.md"),
            "b/DESIGN.md": DesignRecords(),
        },
    )

    report = _measured(
        files,
        _declaration({"a/adherence.toml": SUB, "b/adherence.toml": SUB}),
        facts,
        records,
    )

    traced = [f for f in report.findings if f.check.name == "Trace"]
    assert [f.unit.path for f in traced] == ["a/DESIGN.md"], traced
    assert "Trace" in {c.name for c in report.ran}
    assert any(
        c.check == "Trace" and "b/DESIGN.md" in c.reason for c in report.coverage
    ), [c for c in report.coverage if c.check == "Trace"]
