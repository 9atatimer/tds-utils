"""Design row "Repository code is never run" over every adapter that spawns
a process: git, the Python code model's grimp child, lizard, jscpd and the
decide client (tests/execution_contract.py). Real processes over a
planted repository under tmp_path; a tool that is absent is skipped, never
faked. ast-grep and dependency-cruiser, whose adapters land on another
branch, join this suite when they merge.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from adherence.adapters.decide import DecideDecision
from adherence.adapters.git import GitRepository
from adherence.adapters.jscpd import JscpdDuplication
from adherence.adapters.lizard import LizardComplexity
from adherence.adapters.python_ast import PythonCodeModel
from adherence.container import SHIPPED_VOCABULARY
from adherence.domain.declaration import Declaration
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.questions import TWO_JOBS, Schema, State
from adherence.domain.target import Base, Head
from tests.decide_stub import stub_server
from tests.execution_contract import ExecutionContract

JSCPD = Path(__file__).resolve().parents[2] / "node_modules" / ".bin" / "jscpd"
DECIDE = Path(__file__).resolve().parents[3] / "bin" / "decide"
GIT_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": "/nonexistent",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=GIT_ENV,
    ).stdout.strip()


class TestGitNeverRunsRepositoryCode(ExecutionContract):
    """The repository's own git configuration names programs -- an fsmonitor
    and a hooks directory -- that would leave the mark too."""

    def prepare(self, root: Path, files: Mapping[str, bytes]) -> None:
        super().prepare(root, files)
        _git(root, "init", "-q", "-b", "master")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "planted")
        sentinel = files["setup.py"].decode().split("open(")[1].split(",")[0]
        hook = root / ".git" / "evil-hooks" / "post-index-change"
        hook.parent.mkdir()
        hook.write_text(f"#!/bin/sh\ntouch {sentinel}\n")
        hook.chmod(0o755)
        monitor = root / ".git" / "evil-monitor"
        monitor.write_text(f"#!/bin/sh\ntouch {sentinel}\n")
        monitor.chmod(0o755)
        _git(root, "config", "core.fsmonitor", str(monitor))
        _git(root, "config", "core.hooksPath", str(hook.parent))
        self.revision = _git(root, "rev-parse", "HEAD")

    def run(self, root: Path, files: Mapping[str, bytes]) -> None:
        repository = GitRepository(str(root))
        for at in (Head.working_tree(), Head.staged_index(), Base(self.revision)):
            assert isinstance(repository.tree(at, None), tuple)
            for path in files:
                assert isinstance(repository.read(path, at, None), bytes), path


class TestPythonModelNeverRunsRepositoryCode(ExecutionContract):
    def run(self, root: Path, files: Mapping[str, bytes]) -> None:
        python = {p: d for p, d in files.items() if p.endswith(".py")}
        PythonCodeModel().model(python, Declaration.none, SHIPPED_VOCABULARY, None)


@pytest.mark.skipif(
    importlib.util.find_spec("lizard") is None, reason="lizard is not installed"
)
class TestLizardNeverRunsRepositoryCode(ExecutionContract):
    def run(self, root: Path, files: Mapping[str, bytes]) -> None:
        LizardComplexity().measure(files, None)


@pytest.mark.skipif(
    not JSCPD.is_file(), reason="jscpd is not installed (npm ci --ignore-scripts)"
)
class TestJscpdNeverRunsRepositoryCode(ExecutionContract):
    def run(self, root: Path, files: Mapping[str, bytes]) -> None:
        JscpdDuplication(command=(str(JSCPD),)).measure(files, None)


@pytest.mark.skipif(shutil.which("node") is None, reason="node runs bin/decide")
class TestDecideNeverRunsRepositoryCode(ExecutionContract):
    """The unit's text, and each question's data, go to the decide client
    on its standard input as the record's state, and to nothing else."""

    def own_configuration(self) -> frozenset[str]:
        return frozenset({"DECIDE_BACKEND", "DECIDE_URL"})

    def run(self, root: Path, files: Mapping[str, bytes]) -> None:
        unit = Unit("src/pkg/rules.py", UnitKind.FUNCTION, "price", 3, 6, Layer.DOMAIN)
        state = State(
            unit,
            files["src/pkg/rules.py"].decode(),
            {"two_jobs.1": files["conftest.py"].decode()},
        )
        with stub_server() as stub:
            judge = DecideDecision(
                command=(str(DECIDE), "run", "--model", "clef", "--tool", "adherence"),
                configuration={"DECIDE_BACKEND": "systemone", "DECIDE_URL": stub.url},
            )
            judge.decide(state, Schema({"two_jobs.1": TWO_JOBS}), None)
            assert stub.received, "the record never reached the judge"
