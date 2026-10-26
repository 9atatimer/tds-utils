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


def _revisions(root: Path) -> tuple[str, str]:
    """A repository whose first commit is the fixture's base tree and whose
    second is its head tree; their object ids."""
    base = make_repository(root, base={}, staged={}, working={})
    shutil.copytree(FIXTURE / "base", root, dirs_exist_ok=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    first = _git(root, "rev-parse", "HEAD")
    shutil.copytree(FIXTURE / "head", root, dirs_exist_ok=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "head")
    assert base.revision != first
    return first, _git(root, "rev-parse", "HEAD")


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
    base, head = _revisions(root)
    store = FakeReportStore()

    code, output = _judge(root, base, head, store)

    document = json.loads(output)
    assert document["verdict"] == "lowered", output
    findings = [f for q in document["qualities"] for f in q["findings"]]
    (stub,) = [f for f in findings if f["check"] == "Stub"]
    assert (stub["symbol"], stub["provenance"]) == ("discount", "introduced")
    assert document["recorded"] == {"kept": True, "notice": None}
    assert [r.revision for r in store.scanned] == [head]
    assert code == 1


def test_judge_json_of_the_reverse_change_is_raised(tmp_path: Path) -> None:
    """Given the same two revisions judged the other way round, When the
    head removes the stub, Then it prints the verdict raised, names the
    removed finding, and exits zero."""
    root = tmp_path / "repo"
    base, head = _revisions(root)

    code, output = _judge(root, head, base, FakeReportStore())

    document = json.loads(output)
    assert document["verdict"] == "raised", output
    (removed,) = document["removed"]
    assert (removed["check"], removed["symbol"]) == ("Stub", "discount")
    assert code == 0, output
