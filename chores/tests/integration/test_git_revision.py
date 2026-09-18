"""git_revision against a real temporary repository (real subprocess, so it
lives in integration/ per the testing-python skill)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from chores.adapters.definitions import git_revision

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def test_git_revision_reports_sha_dirty_and_untracked(tmp_path: Path) -> None:
    assert git_revision(tmp_path) == "untracked"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
    }
    (tmp_path / "a").write_text("1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a"], check=True, env=env)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "one",
        ],
        check=True,
        env=env,
    )
    clean = git_revision(tmp_path)
    assert len(clean) == 40 and "-dirty" not in clean
    (tmp_path / "a").write_text("2")
    assert git_revision(tmp_path) == clean + "-dirty"
