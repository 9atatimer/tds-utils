"""Real git in a throwaway repository, isolated from the machine's own
configuration: the environment every test's git runs under, the command
itself, and a repository built from a base commit, a staged index and a
working tree."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Collection
from pathlib import Path

from adherence.domain.target import Base
from tests.repository_contract import Files

GIT_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": "/nonexistent",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(root: Path, *args: str) -> str:
    """`git -C root <args>` under GIT_ENV; its output, stripped."""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=GIT_ENV,
    ).stdout.strip()


def _write(root: Path, files: Files) -> None:
    for path, data in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)


def make_repository(
    root: Path,
    *,
    base: Files,
    staged: Files,
    working: Files,
    deleted: Collection[str] = (),
) -> Base:
    """A repository at `root` whose one commit holds `base`, whose index
    adds `staged` and drops `deleted`, and whose working tree adds
    `working`; the base commit."""
    git(root.parent, "init", "-q", "-b", "master", str(root))
    _write(root, base)
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", "base")
    revision = git(root, "rev-parse", "HEAD")
    _write(root, staged)
    for path in deleted:
        (root / path).unlink()
    git(root, "add", "-A")
    _write(root, working)
    return Base(revision)
