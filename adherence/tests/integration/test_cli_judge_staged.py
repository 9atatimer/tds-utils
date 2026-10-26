"""`adhere judge --staged --json`, the hook stage, through the composition
root over the judge fixture: the staged index judged against HEAD under
the commit-time bound, with real git and the real Python analyzer. The
hook's exit mapping: lowered stops the commit; inconclusive lets it
proceed (ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism > Judging a change, The
hook). The task-065 done check: a fixture analyzer that sleeps past the
bound is ended and the commit proceeds with the unfinished checks as
coverage."""

from __future__ import annotations

import functools
import json
import shutil
import sys
import time
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeComplexity, FakeDuplication, FakeReportStore
from adherence.adapters.inline_worker import InlineWorker
from adherence.adapters.lizard import LizardComplexity
from adherence.cli.main import main
from adherence.container import Container, build
from tests.integration.test_git_repository import _git, make_repository

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "judge"
SLEEPER = Path(__file__).resolve().parents[1] / "fixtures" / "analyzers" / "sleeper.py"


def _staged(root: Path, *, committed: str, staged: str) -> None:
    """A repository whose HEAD holds one fixture tree and whose index stages
    another over it, as a commit about to be made does."""
    make_repository(root, base={}, staged={}, working={})
    shutil.copytree(FIXTURE / committed, root, dirs_exist_ok=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", committed)
    shutil.copytree(FIXTURE / staged, root, dirs_exist_ok=True)
    _git(root, "add", "-A")


def _judge_staged(root: Path, builder: functools.partial[Container]) -> tuple[int, str]:
    result = CliRunner().invoke(
        main, ["judge", "--root", str(root), "--staged", "--json"], obj=builder
    )
    return result.exit_code, result.output


def test_judge_staged_stub_is_lowered_and_stops_the_commit(tmp_path: Path) -> None:
    """Given HEAD at the base and a staged stubbed domain rule, When `adhere
    judge --staged --json` runs in the hook, Then it prints the verdict
    lowered with the stub introduced and exits non-zero."""
    root = tmp_path / "repo"
    _staged(root, committed="base", staged="head")
    builder = functools.partial(
        build,
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        reports=FakeReportStore(),
        worker=InlineWorker(),
    )

    code, output = _judge_staged(root, builder)

    document = json.loads(output)
    assert document["verdict"] == "lowered", output
    findings = [f for q in document["qualities"] for f in q["findings"]]
    (stub,) = [f for f in findings if f["check"] == "Stub"]
    assert stub["provenance"] == "introduced"
    assert code == 1


def test_judge_staged_past_the_bound_is_coverage_and_the_commit_proceeds(
    tmp_path: Path,
) -> None:
    """Given a staged change and a complexity analyzer that sleeps far past
    its bound, When `adhere judge --staged --json` runs in the hook with its
    own worker, Then the analyzer is ended, the checks that did not finish
    are coverage, the verdict is inconclusive, and it exits zero so the
    commit proceeds."""
    root = tmp_path / "repo"
    _staged(root, committed="head", staged="fixed")
    builder = functools.partial(
        build,
        complexity=LizardComplexity(
            command=(sys.executable, "-I", str(SLEEPER)), bound=0.5
        ),
        duplication=FakeDuplication(),
        reports=FakeReportStore(),
    )
    started = time.monotonic()

    code, output = _judge_staged(root, builder)

    document = json.loads(output)
    assert document["verdict"] == "inconclusive", output
    timed_out = {c["check"] for c in document["coverage"] if "timed out" in c["reason"]}
    assert {"Complexity", "Duplication"} <= timed_out, output
    assert code == 0, output
    assert time.monotonic() - started < 60
