"""measure, the report-level rows (DESIGN.ARCH-ADHERENCE.md, Behaviors;
ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface), driven by its signature
with a fake behind every port."""

from __future__ import annotations

from adherence.adapters.fakes import FakeCodeModel, FakeComplexity, FakeDuplication
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, DeclarationUnreadable
from adherence.domain.model import (
    Access,
    AccessKind,
    CodeLanguage,
    CodeModel,
    ImportEdge,
    Layer,
    Unit,
    UnitKind,
    Unparsed,
)
from adherence.domain.parameters import Limits
from adherence.domain.qualities import CATALOG, CheckKind, Quality
from adherence.ports.repository import Refused
from tests.measure_kit import HEXAGON, declared, measure_with

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


def test_measure_of_a_declared_repository_reports_per_quality_with_reasons() -> None:
    """Given a declared repository, When a run is asked for, Then the report
    holds, per quality, the checks that ran and each finding with its unit,
    check, kind, layer and evidence; every other check, and every source not
    measured, is coverage with its reason."""
    files = {
        RULES: b"def load():\n    return os.environ['K']\n",
        "src/app/domain/secret.py": Refused("src/app/domain/secret.py", "a link"),
        "src/app/domain/broken.py": b"def (:\n",
        "scratch.py": b"x = 1\n",
        "README.md": b"# not a source\n",
    }
    facts = CodeModel(
        units=(Unit(RULES, UnitKind.FUNCTION, "load", 1, 2, None),),
        accesses=(Access(RULES, 2, "load", AccessKind.ENVIRONMENT, "os.environ"),),
        unparsed=(Unparsed("src/app/domain/broken.py", "not Python: line 1"),),
    )

    report = measure_with(files, facts)

    assert "Grep" in [c.name for c in report.ran_in(Quality.HEXAGONAL)]
    (leak,) = report.findings_of(Quality.HEXAGONAL)
    assert (leak.check.name, leak.kind, leak.layer) == (
        "Grep",
        CheckKind.RULE,
        Layer.DOMAIN,
    )
    assert (leak.unit.path, leak.unit.symbol) == (RULES, "load")
    assert (leak.evidence.path, leak.evidence.line) == (RULES, 2)
    ran = {c.name for c in report.ran}
    covered = {c.check: c.reason for c in report.coverage if c.check}
    assert all(c.name in ran or covered.get(c.name) for c in CATALOG)
    assert "change" in covered["Covered"] and "change" in covered["Record kept"]
    by_path = {c.path: c.reason for c in report.coverage if c.path}
    assert "a link" in by_path["src/app/domain/secret.py"]
    assert "line 1" in by_path["src/app/domain/broken.py"]
    assert "layer" in by_path["scratch.py"]
    assert "README.md" not in by_path


def test_measure_whose_ports_time_out_reports_them_as_coverage() -> None:
    """Given an analyzer and the complexity and duplication tooling that each
    answer TimedOut, When a run is asked for, Then the report names each as
    coverage, never as a clean result."""
    files = {RULES: b"x = 1\n"}

    report = measure_with(
        files,
        analyzers={CodeLanguage.PYTHON: FakeCodeModel(now=2.0)},
        deadline=Deadline(epoch_seconds=1.0),
        complexity=FakeComplexity(TimedOut("measure complexity")),
        duplication=FakeDuplication(TimedOut("find clones")),
    )

    reasons = [c.reason for c in report.coverage]
    assert any(c.path == RULES and "timed out" in c.reason for c in report.coverage)
    assert any("measure complexity" in r for r in reasons)
    assert any("find clones" in r for r in reasons)


def test_measure_of_an_undeclared_repository_runs_what_needs_no_declaration() -> None:
    """Given a repository with no declaration, When a run is asked for, Then
    the checks that need no declaration run (Arrow finds the cycle), and
    coverage names every check that needed one."""
    values = "src/app/domain/values.py"
    files = {RULES: b"import values\nimport requests\n", values: b"import rules\n"}
    facts = CodeModel(
        imports=(
            ImportEdge(RULES, "values", 1, "import values", values),
            ImportEdge(RULES, "requests", 2, "import requests", None),
            ImportEdge(values, "rules", 1, "import rules", RULES),
        )
    )

    report = measure_with(files, facts, Declaration.none)

    assert {c.name for c in report.ran_in(Quality.HEXAGONAL)} == {"Arrow"}
    assert [f.check.name for f in report.findings] == ["Arrow"]
    needed = {c.check for c in report.coverage if c.check and "declaration" in c.reason}
    assert {"Grep", "Arrow", "Swap", "Change"} <= needed


def test_measure_reports_a_refused_exemption_of_a_declared_check() -> None:
    """Given a declaration that exempts Covered and Record kept, When a run is
    asked for, Then each exemption is refused and the report says so, with
    the check, the unit and why."""
    declaration = declared(
        HEXAGON
        + b'[[exemptions]]\ncheck = "Covered"\nunit = "src/app/new.py"\nreason = "r"\n'
        + b'[[exemptions]]\ncheck = "Record kept"\nunit = "docs/x.md"\nreason = "r"\n'
    )

    report = measure_with({RULES: b"x = 1\n"}, declaration=declaration)

    messages = [n.message for n in report.notices]
    assert any("Covered" in m and "src/app/new.py" in m for m in messages)
    assert any("Record kept" in m and "docs/x.md" in m for m in messages)
    assert all("Declared" in m for m in messages)


def test_measure_reports_each_unit_in_an_unmeasured_language() -> None:
    """Given sources in TypeScript and shell and no analyzer for them, When a
    run is asked for, Then coverage names each unit and its language."""
    files = {RULES: b"x = 1\n", "web/app.ts": b"let x = 1\n", "bin/run.sh": b"true\n"}

    report = measure_with(files)

    by_path = {c.path: c.reason for c in report.coverage if c.path}
    assert "typescript" in by_path["web/app.ts"]
    assert "shell" in by_path["bin/run.sh"]
    assert RULES not in by_path


def test_measure_with_no_analyzer_for_python_reports_its_units() -> None:
    """Given Python sources and no analyzer bound for Python, When a run is
    asked for, Then coverage names each Python unit and the language."""
    report = measure_with({RULES: b"x = 1\n"}, analyzers={})

    assert any(c.path == RULES and "python" in c.reason for c in report.coverage)


LONG = "k = os.environ['" + "x" * 300 + "']"
BODY = f"def load():\n    secret = 'body line'\n    {LONG}\n    return k\n".encode()
LOAD = CodeModel(
    units=(Unit(RULES, UnitKind.FUNCTION, "load", 1, 4, None),),
    accesses=(Access(RULES, 3, "load", AccessKind.ENVIRONMENT, "os.environ"),),
)


def test_measure_quotes_the_offending_line_and_no_more_of_the_body() -> None:
    """Given a finding on a line of a function, When the report is written,
    Then it holds the unit's path and symbol and the offending line as the
    evidence, never another line of the unit's body."""
    report = measure_with({RULES: BODY}, LOAD, limits=Limits(evidence_bound=1000))

    (leak,) = [f for f in report.findings if f.check.name == "Grep"]
    assert (leak.unit.path, leak.unit.symbol, leak.evidence.line) == (RULES, "load", 3)
    assert leak.evidence.text == LONG
    assert "body line" not in leak.evidence.text and "return" not in leak.evidence.text


def test_measure_cuts_the_quoted_line_at_the_evidence_bound() -> None:
    """Given an offending line longer than the evidence bound, When the report
    is written, Then the evidence quotes no more than the bound."""
    report = measure_with({RULES: BODY}, LOAD, limits=Limits(evidence_bound=40))

    (leak,) = [f for f in report.findings if f.check.name == "Grep"]
    assert leak.evidence.text == LONG[:40]


def test_measure_of_a_repository_that_cannot_be_listed_is_not_run() -> None:
    """Given a repository whose tree cannot be listed, or not within the
    deadline, When a run is asked for, Then the report is not run and names
    why, and nothing reads as a pass."""
    for unlisted in (Refused(".", "not a git repository"), TimedOut("list the tree")):
        report = measure_with({RULES: b"x = 1\n"}, unlisted=unlisted)

        assert report.not_run_reason is not None
        assert ("not a git repository" in report.not_run_reason) or (
            "list the tree" in report.not_run_reason
        )
        assert report.ran == () and report.findings == ()
