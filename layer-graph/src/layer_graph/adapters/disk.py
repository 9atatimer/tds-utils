"""The repository on disk: a directory walk, file reads, and git for the
remote and HEAD. The only module that touches the file system or runs a
process."""

import os
import posixpath
import re
import subprocess
from pathlib import Path

# --- Constants ---------------------------------------------------------------

# Build output, dependencies and caches: never units, never walked.
EXCLUDED_DIRECTORIES = frozenset(
    {
        "node_modules",
        ".nuxt",
        ".output",
        "dist",
        "build",
        "__pycache__",
        ".git",
        ".venv",
    }
)
GIT_TIMEOUT_SECONDS = 10
_REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


# --- Pure helpers ------------------------------------------------------------


def repo_name(remote_url: str) -> str | None:
    """owner/name from a git remote URL (ssh or https), or None."""
    match = _REMOTE.search(remote_url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


# --- Adapter -----------------------------------------------------------------


class DiskRepository:
    """A RepoSource over a directory on disk."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> str:
        """The repository root as an absolute path."""
        return str(self._root)

    def files(self) -> list[str]:
        """Every file under the root, excluded directories pruned."""
        found: list[str] = []
        for directory, subdirectories, names in os.walk(self._root):
            subdirectories[:] = sorted(
                d for d in subdirectories if d not in EXCLUDED_DIRECTORIES
            )
            relative = Path(directory).relative_to(self._root).as_posix()
            prefix = "" if relative == "." else relative + "/"
            found.extend(prefix + name for name in names)
        return sorted(found)

    def read_text(self, path: str) -> str | None:
        """A file's text; None when unreadable or outside the root."""
        normal = posixpath.normpath(path)
        if normal.startswith("../") or normal == ".." or normal.startswith("/"):
            return None
        try:
            return (self._root / normal).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _git(self, *args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", "-C", str(self._root), *args],
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    def identity(self) -> tuple[str | None, str | None]:
        """owner/name of the origin remote and the HEAD commit, when the root
        is itself the top of a git work tree; (None, None) otherwise."""
        top = self._git("rev-parse", "--show-toplevel")
        if top is None or Path(top).resolve() != self._root:
            return (None, None)
        remote = self._git("remote", "get-url", "origin")
        return (repo_name(remote) if remote else None, self._git("rev-parse", "HEAD"))
