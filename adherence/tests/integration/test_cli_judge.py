"""`adhere judge --base --head --json` through the composition root over two
revisions of the judge fixture: real git and the real Python analyzer, with
complexity, duplication and the report store overridden by their fakes. The
task-062 done check: the verdict is the design's table's (DESIGN.ARCH-
ADHERENCE.md, Judging a change)."""

from __future__ import annotations

import functools
import json
import shutil
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeComplexity, FakeDuplication, FakeReportStore
from adherence.cli.main import main
from adherence.container import build
from tests.integration.test_git_repository import _git, make_repository

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "judge"


def _revisions(root: Path) -> dict[str, str]:
    """A repository with a commit per fixture tree, in order: base, head
    (adds a stubbed rule), fixed (implements it); their object ids."""
    make_repository(root, base={}, staged={}, working={})
    revisions: dict[str, str] = {}
    for tree in ("base", "head", "fixed"):
        shutil.copytree(FIXTURE / tree, root, dirs_exist_ok=True)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", tree)
        revisions[tree] = _git(root, "rev-parse", "HEAD")
    return revisions


def _judge(root: Path, base: str, head: str, store: FakeReportStore) -> tuple[int, str]:
    builder = functools.partial(
        build,
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        reports=store,
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
