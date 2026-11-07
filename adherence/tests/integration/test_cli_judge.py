"""`adhere judge --base --head --json` through the composition root over two
revisions of the judge fixture: real git and the real Python analyzer, with
complexity, duplication, the report store and the judge overridden by their
fakes -- the judge passes every judged question, so the verdict is the rule
checks'. The task-062 done check: the verdict is the design's table's (DESIGN.ARCH-
ADHERENCE.md, Judging a change)."""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from adherence.adapters.fakes import (
    FakeComplexity,
    FakeDuplication,
    FakeRecords,
    FakeReportStore,
)
from adherence.cli.main import main
from adherence.container import Container, build
from tests import shell_fixture
from tests.fixture_tree import plant
from tests.git_kit import git, make_repository
from tests.json_schema import sarif_violations
from tests.judge_kit import passing_judge

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "judge"
TYPESCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "typescript"


def _revisions(root: Path) -> dict[str, str]:
    """A repository with a commit per fixture tree, in order: base, head
    (adds a stubbed rule), fixed (implements it); their object ids."""
    make_repository(root, base={}, staged={}, working={})
    revisions: dict[str, str] = {}
    for tree in ("base", "head", "fixed"):
        plant(FIXTURE / tree, root)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", tree)
        revisions[tree] = git(root, "rev-parse", "HEAD")
    return revisions


def _over_real_git() -> functools.partial[Container]:
    """The composition root over real git and the real Python analyzer, the
    metrics, the report store and the judge faked, and no environment."""
    return functools.partial(
        build,
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        reports=FakeReportStore(),
        judge=passing_judge(),
        environment={},
    )


def _judge(root: Path, base: str, head: str, store: FakeReportStore) -> tuple[int, str]:
    builder = functools.partial(
        build,
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        reports=store,
        judge=passing_judge(),
    )
    result = CliRunner().invoke(
        main,
        ["judge", "--root", str(root), "--base", base, "--head", head, "--json"],
        obj=builder,
    )
    return result.exit_code, result.output


def test_judge_json_of_a_head_that_adds_a_stub_is_lowered(tmp_path: Path) -> None:
    """Given a base and a head that adds a stubbed domain rule, When `adhere
    judge --base --head --json` runs, Then it prints the verdict lowered with
    the stub marked introduced, keeps the report, and exits non-zero."""
    root = tmp_path / "repo"
    revisions = _revisions(root)
    store = FakeReportStore()

    code, output = _judge(root, revisions["base"], revisions["head"], store)

    document = json.loads(output)
    assert document["verdict"] == "lowered", output
    findings = [f for q in document["qualities"] for f in q["findings"]]
    (stub,) = [f for f in findings if f["check"] == "Stub"]
    assert (stub["symbol"], stub["provenance"]) == ("discount", "introduced")
    assert document["recorded"] == {"kept": True, "notice": None}
    assert [r.revision for r in store.scanned] == [revisions["head"]]
    assert code == 1


def test_judge_json_of_a_head_that_implements_the_stub_is_raised(
    tmp_path: Path,
) -> None:
    """Given the stubbed rule at the base and implemented at the head, When
    `adhere judge` runs, Then it prints the verdict raised, names the
    removed finding, and exits zero."""
    root = tmp_path / "repo"
    revisions = _revisions(root)

    code, output = _judge(
        root, revisions["head"], revisions["fixed"], FakeReportStore()
    )

    document = json.loads(output)
    assert document["verdict"] == "raised", output
    (removed,) = document["removed"]
    assert (removed["check"], removed["symbol"]) == ("Stub", "discount")
    assert code == 0, output


def test_judge_json_of_a_head_that_deletes_the_stub_is_held(tmp_path: Path) -> None:
    """Given the stubbed rule at the base and deleted at the head, When
    `adhere judge` runs, Then the flaw is neither introduced nor removed and
    it prints the verdict held."""
    root = tmp_path / "repo"
    revisions = _revisions(root)

    code, output = _judge(root, revisions["head"], revisions["base"], FakeReportStore())

    document = json.loads(output)
    assert (document["verdict"], document["removed"]) == ("held", []), output
    assert code == 0, output


def _added(root: Path, fixture: Path, path: str) -> tuple[str, str]:
    """A repository holding the fixture without one file at the base and
    whole at the head; their object ids."""
    make_repository(root, base={}, staged={}, working={})
    plant(fixture, root)
    held = (root / path).read_bytes()
    (root / path).unlink()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD")
    (root / path).write_bytes(held)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "head")
    return base, git(root, "rev-parse", "HEAD")


def _judged(root: Path, base: str, head: str) -> dict[str, object]:
    builder = functools.partial(
        build,
        records=FakeRecords({}),
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        reports=FakeReportStore(),
    )
    result = CliRunner().invoke(
        main,
        ["judge", "--root", str(root), "--base", base, "--head", head, "--json"],
        obj=builder,
    )
    document = json.loads(result.output)
    assert isinstance(document, dict), result.output
    return document


def _provenances(document: dict[str, object]) -> set[tuple[str, str, str, str]]:
    qualities = document["qualities"]
    assert isinstance(qualities, list)
    return {
        (f["check"], f["path"], f["symbol"] or "", f["provenance"])
        for q in qualities
        for f in q["findings"]
    }


def test_judge_of_a_head_that_adds_a_shell_script_reads_it(tmp_path: Path) -> None:
    """Given the shell fixture with its release script added by the head,
    When `adhere judge` runs through the composition root, Then the shell
    analyzer reads both revisions: the script's stub is introduced, the
    other script's misplaced entry point is existing, and a check that does
    not read shell says so of the added script."""
    root = tmp_path / "repo"
    base, head = _added(root, shell_fixture.ROOT, "bin/release.sh")

    document = _judged(root, base, head)

    assert document["verdict"] == "lowered", document
    found = _provenances(document)
    assert ("Stub", "bin/release.sh", "rollback", "introduced") in found
    assert ("Anatomy", "bin/backwards.sh", "", "existing") in found
    coverage = document["coverage"]
    assert isinstance(coverage, list)
    reasons = {(c["check"], c["path"]): c["reason"] for c in coverage}
    assert reasons[("Grep", "bin/release.sh")] == "does not read shell"


def test_judge_of_a_head_that_adds_a_typescript_file_reads_it(
    tmp_path: Path,
) -> None:
    """Given the TypeScript fixture with its application module added by
    the head, When `adhere judge` runs through the composition root, Then
    the TypeScript analyzer reads both revisions: the module's stub is
    introduced and the domain rule's stub is existing."""
    root = tmp_path / "repo"
    base, head = _added(root, TYPESCRIPT, "lib/tool/run.ts")

    document = _judged(root, base, head)

    assert document["verdict"] == "lowered", document
    found = _provenances(document)
    assert ("Stub", "lib/tool/run.ts", "closeOrder", "introduced") in found
    assert ("Stub", "lib/tool/rules.ts", "unfinished", "existing") in found


def test_judge_sarif_of_the_fixture_conforms_to_sarif_2_1_0(tmp_path: Path) -> None:
    """Given the judge fixture's base and the head that adds a stub, When
    `adhere judge --base --head --format sarif` runs with real
    git and the real Python analyzer, Then the log conforms to the official
    SARIF 2.1.0 schema and its introduced Stub result is an error at the
    stub's line (the task-066 done check)."""
    root = tmp_path / "repo"
    revisions = _revisions(root)
    builder = _over_real_git()

    result = CliRunner().invoke(
        main,
        [
            *("judge", "--root", str(root)),
            *("--base", revisions["base"], "--head", revisions["head"]),
            *("--format", "sarif"),
        ],
        obj=builder,
    )

    document = json.loads(result.output)
    assert sarif_violations(document) == []
    (stub,) = [r for r in document["runs"][0]["results"] if r["ruleId"] == "stub"]
    assert (stub["level"], stub["properties"]["provenance"]) == ("error", "introduced")
    assert result.exit_code == 1


# A committed path no UTF-8 decodes: byte 0xff, which the git adapter
# carries through as a lone surrogate (surrogateescape).
UNDECODABLE = os.fsdecode(b"src/tool/domain/rul\xffs.py")


def _undecodable_revisions(root: Path) -> tuple[str, str]:
    """A base of the fixture's base tree and a head that adds the fixture's
    stubbed rule under UNDECODABLE, written into the index by object id so
    a filesystem that refuses the name cannot refuse the commit."""
    make_repository(root, base={}, staged={}, working={})
    plant(FIXTURE / "base", root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD")
    blob = git(
        root,
        "hash-object",
        "-w",
        str(FIXTURE / "head" / "src" / "tool" / "domain" / "rules.py"),
    )
    git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{UNDECODABLE}")
    git(root, "commit", "-q", "-m", "undecodable")
    return base, git(root, "rev-parse", "HEAD")


@pytest.mark.parametrize("output_format", ["terminal", "summary", "sarif"])
def test_judge_of_a_path_no_utf8_decodes_keeps_its_verdict(
    tmp_path: Path, output_format: str
) -> None:
    """Given a head that commits a stubbed rule under a path carrying byte
    0xff, When `adhere judge --format <terminal|summary|sarif>` runs, Then
    the report prints with the byte replaced for display, the SARIF uri
    still percent-encodes the real byte and the log conforms to SARIF
    2.1.0, and the exit status is the verdict's, not a traceback's."""
    root = tmp_path / "repo"
    base, head = _undecodable_revisions(root)
    builder = _over_real_git()

    result = CliRunner().invoke(
        main,
        [
            *("judge", "--root", str(root), "--base", base, "--head", head),
            *("--format", output_format),
        ],
        obj=builder,
    )

    assert isinstance(result.exception, SystemExit), result.exception
    assert result.exit_code == 1
    if output_format == "sarif":
        document = json.loads(result.output)
        assert sarif_violations(document) == []
        assert "\\udcff" not in result.output
        (stub,) = [r for r in document["runs"][0]["results"] if r["ruleId"] == "stub"]
        uri = stub["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert uri == "src/tool/domain/rul%FFs.py"
    else:
        assert "lowered" in result.output.splitlines()[0]
        assert "rul�s" in result.output
