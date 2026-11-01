"""`adhere judge --staged --json`, the hook stage, through the composition
root over the judge fixture: the staged index judged against HEAD under
the commit-time bound, with real git and the real Python analyzer. The
hook's exit mapping: lowered stops the commit; inconclusive lets it
proceed (ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism > Judging a change, The
hook). The task-065 done check: a fixture analyzer that sleeps past the
bound is ended and the commit proceeds with the unfinished checks as
coverage -- by its adapter at its own bound, and by the worker at the
commit-time deadline when it ignores that deadline. Every run that could
hang is watched from a daemon thread, so it fails instead."""

from __future__ import annotations

import functools
import json
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeComplexity, FakeDuplication, FakeReportStore
from adherence.adapters.inline_worker import InlineWorker
from adherence.adapters.lizard import LizardComplexity
from adherence.cli.main import main
from adherence.container import SHIPPED_LIMITS, Container, build
from adherence.domain.report import ENDED
from tests.integration.test_git_repository import _git, make_repository
from tests.worker_jobs import OutlivesTheDeadline

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "judge"
SLEEPER = Path(__file__).resolve().parents[1] / "fixtures" / "analyzers" / "sleeper.py"
# How long past the commit-time bound the hook may take before it is hung.
GRACE = 30.0
# How long the ended analyzer may take to be reaped by init.
REAPED_WITHIN = 5.0
LINK = "src/tool/domain/link.py"


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


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float) -> bool:
    give_up = time.monotonic() + seconds
    while _is_running(pid):
        if time.monotonic() > give_up:
            return False
        time.sleep(0.05)
    return True


def _watched_judge_staged(
    root: Path, builder: functools.partial[Container], within: float
) -> tuple[int, str] | None:
    """`adhere judge --staged --json`'s exit code and output, or None when
    it did not answer within `within` seconds."""
    answers: list[tuple[int, str]] = []
    thread = threading.Thread(
        target=lambda: answers.append(_judge_staged(root, builder)), daemon=True
    )
    thread.start()
    thread.join(within)
    return answers[0] if answers else None


def test_judge_staged_whose_analyzer_outlives_the_deadline_is_ended_by_the_worker(
    tmp_path: Path,
) -> None:
    """Given a staged change holding a file that cannot be read, and a
    complexity analyzer that ignores the deadline and sleeps past it, When
    `adhere judge --staged --json` runs in the hook, Then the worker ends
    the run at the commit-time deadline and the analyzer with it, the
    unfinished checks are coverage beside the unreadable file, the verdict
    is inconclusive, and it exits zero so the commit proceeds."""
    root = tmp_path / "repo"
    _staged(root, committed="head", staged="fixed")
    (root / LINK).symlink_to("rules.py")
    _git(root, "add", "-A")
    pid_file = tmp_path / "analyzer.pid"
    builder = functools.partial(
        build,
        complexity=OutlivesTheDeadline((sys.executable, "-I", str(SLEEPER)), pid_file),
        duplication=FakeDuplication(),
        reports=FakeReportStore(),
    )
    bound = SHIPPED_LIMITS.commit_time_bound or 0.0

    answer = _watched_judge_staged(root, builder, bound + GRACE)

    analyzer = int(pid_file.read_text(encoding="utf-8")) if pid_file.exists() else None
    try:
        assert answer is not None, "the hook did not end within its bound"
        code, output = answer
        document = json.loads(output)
        assert document["verdict"] == "inconclusive", output
        assert any("ended at the deadline" in r for r in document["reasons"]), output
        ended = {c["check"] for c in document["coverage"] if c["reason"] == ENDED}
        assert "Complexity" in ended, output
        assert any(
            c["path"] == LINK and "symbolic link" in c["reason"]
            for c in document["coverage"]
        ), output
        assert code == 0, output
        assert analyzer is not None, "the analyzer never started"
        assert _gone_within(analyzer, REAPED_WITHIN), "the analyzer outlived the run"
    finally:
        if analyzer is not None and _is_running(analyzer):
            os.kill(analyzer, signal.SIGKILL)
