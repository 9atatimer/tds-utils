"""Shell adapters for goldfish.

Each function shells out to git/gh/ps/lsof/find and parses the result via
core.py. Failures degrade to None / empty-list rather than raising; goldfish
should always render *something*, even when gh is missing or a repo is broken.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from core import (
    AgentSession,
    ClonesCache,
    GithubInfo,
    LocalInfo,
    GitDirtyState,
    enclosing_repo,
    parse_clones_cache,
    parse_gh_repo_list,
    parse_git_porcelain,
    parse_lsof_cwd,
    parse_ps,
    parse_todo_plan,
    serialize_clones_cache,
)


# --- Process helpers ---------------------------------------------------------

def _run(cmd: list[str], *, timeout: float = 10.0, cwd: str | None = None) -> str:
    """Run a command and return stdout. Empty string on any failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    return result.stdout


def have(cmd: str) -> bool:
    """True if `cmd` is on $PATH."""
    return shutil.which(cmd) is not None


# --- GitHub adapter ----------------------------------------------------------

def gh_list_repos(orgs: list[str], *, limit: int = 1000) -> list[GithubInfo]:
    """List repos across the given owners/orgs via `gh repo list`."""
    if not have("gh"):
        return []
    out: list[GithubInfo] = []
    for org in orgs:
        raw = _run([
            "gh", "repo", "list", org,
            "--json", "nameWithOwner,pushedAt,isArchived",
            "--limit", str(limit),
        ], timeout=30.0)
        if raw.strip():
            out.extend(parse_gh_repo_list(raw))
    return out


def gh_open_pr_counts(orgs: list[str]) -> dict[str, int]:
    """Return {nameWithOwner: open_pr_count} across the given owners."""
    if not have("gh"):
        return {}
    counts: dict[str, int] = {}
    for org in orgs:
        raw = _run([
            "gh", "search", "prs",
            "--owner", org,
            "--state", "open",
            "--json", "repository",
            "--limit", "1000",
        ], timeout=30.0)
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for entry in data:
            name = entry.get("repository", {}).get("nameWithOwner")
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


# --- Disk adapter ------------------------------------------------------------

def find_local_clones(roots: list[Path], *, max_depth: int = 6) -> dict[str, Path]:
    """Walk `roots` for .git directories. Return {name_with_owner: working_copy_path}."""
    out: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        git_dirs = _find_git_dirs(root, max_depth)
        for git_dir in git_dirs:
            workdir = git_dir.parent
            remote = _git_remote_origin(workdir)
            name = _name_with_owner(remote)
            if name and name not in out:
                out[name] = workdir
    return out


# --- Clones cache (G3) -------------------------------------------------------

CLONES_CACHE_TTL_SECONDS = 24 * 60 * 60


def clones_cache_path() -> Path:
    """Cache file path. Uses $XDG_CACHE_HOME if set, else ~/.cache/."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "goldfish" / "clones.json"


def load_cached_clones() -> ClonesCache | None:
    """Read the cache file. Returns None if missing or malformed."""
    path = clones_cache_path()
    if not path.exists():
        return None
    try:
        return parse_clones_cache(path.read_text())
    except (OSError, UnicodeDecodeError):
        return None


def save_cached_clones(clones: dict[str, Path]) -> None:
    """Atomically write the cache file. Errors are silently swallowed."""
    from datetime import datetime, timezone
    path = clones_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(serialize_clones_cache(clones, saved_at=datetime.now(timezone.utc)))
        tmp.replace(path)
    except OSError:
        pass


def cached_clones_fresh(cache: ClonesCache, *, ttl_seconds: int = CLONES_CACHE_TTL_SECONDS) -> bool:
    """True if the cache is younger than the TTL and every cached path still has .git/."""
    from datetime import datetime, timezone
    age = (datetime.now(timezone.utc) - cache.saved_at).total_seconds()
    if age > ttl_seconds:
        return False
    return all((p / ".git").exists() for p in cache.clones.values())


def _find_git_dirs(root: Path, max_depth: int) -> list[Path]:
    """Use `find` to locate .git directories under root, skipping hidden parents."""
    raw = _run([
        "find", str(root),
        "-maxdepth", str(max_depth),
        "-type", "d",
        "-name", ".git",
        "-not", "-path", "*/.*/.git",
    ], timeout=60.0)
    return [Path(p) for p in raw.splitlines() if p]


_REMOTE_PATTERNS = (
    "git@github.com:",
    "https://github.com/",
    "ssh://git@github.com/",
)


def _git_remote_origin(workdir: Path) -> str:
    return _run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=str(workdir),
        timeout=5.0,
    ).strip()


def _name_with_owner(remote: str) -> str | None:
    """Extract `owner/repo` from a github remote URL, or None."""
    for prefix in _REMOTE_PATTERNS:
        if remote.startswith(prefix):
            tail = remote[len(prefix):]
            if tail.endswith(".git"):
                tail = tail[:-4]
            tail = tail.strip("/")
            if "/" in tail:
                return tail
    return None


def inspect_local(workdir: Path) -> LocalInfo:
    """Inspect a working tree: dirty, ahead/behind, last commit, next task."""
    porcelain = _run(
        ["git", "status", "--porcelain=v1", "-b"],
        cwd=str(workdir),
        timeout=10.0,
    )
    state: GitDirtyState = parse_git_porcelain(porcelain) if porcelain else GitDirtyState(
        branch="", is_dirty=False, ahead=0, behind=0
    )
    last = _run(
        ["git", "log", "-1", "--format=%cI"],
        cwd=str(workdir),
        timeout=5.0,
    ).strip()
    last_dt = _parse_iso_safe(last)
    todo_path = workdir / "TODO_PLAN.md"
    next_task = None
    if todo_path.exists():
        try:
            next_task = parse_todo_plan(todo_path.read_text())
        except (OSError, UnicodeDecodeError):
            next_task = None
    return LocalInfo(
        path=workdir,
        is_dirty=state.is_dirty,
        ahead=state.ahead,
        behind=state.behind,
        branch=state.branch,
        last_commit_at=last_dt,
        next_task=next_task,
    )


def _parse_iso_safe(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def fetch_remote_todo_plan(name_with_owner: str) -> str | None:
    """Fetch TODO_PLAN.md from GitHub via gh api. Returns text or None."""
    if not have("gh"):
        return None
    raw = _run([
        "gh", "api",
        f"repos/{name_with_owner}/contents/TODO_PLAN.md",
        "-H", "Accept: application/vnd.github.raw",
    ], timeout=10.0)
    return raw or None


# --- Process adapter ---------------------------------------------------------

def running_agents(known: set[str], local_clones: dict[str, Path]) -> list[AgentSession]:
    """Find running processes whose name matches `known` and whose cwd is in a clone."""
    ps_out = _run(["ps", "-axo", "pid=,comm="], timeout=5.0)
    if not ps_out:
        return []
    candidates = parse_ps(ps_out, known=known)
    repo_paths = set(local_clones.values())
    sessions: list[AgentSession] = []
    for pid, name in candidates:
        cwd = _proc_cwd(pid)
        if cwd is None:
            continue
        repo = enclosing_repo(cwd, repo_paths)
        if repo is not None:
            sessions.append(AgentSession(pid=pid, name=name, repo_path=repo))
    return sessions


def all_processes_in_clones(local_clones: dict[str, Path]) -> list[AgentSession]:
    """Find every running process whose cwd is inside a tracked repo (G6 verbose).

    No name whitelist applied; for catching agents launched through a wrapper
    (e.g. `python3 launcher.py` re-execing claude) that the agent whitelist
    would miss.
    """
    ps_out = _run(["ps", "-axo", "pid=,comm="], timeout=5.0)
    if not ps_out:
        return []
    repo_paths = set(local_clones.values())
    sessions: list[AgentSession] = []
    for line in ps_out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        name = parts[1].rsplit("/", 1)[-1]
        cwd = _proc_cwd(pid)
        if cwd is None:
            continue
        repo = enclosing_repo(cwd, repo_paths)
        if repo is not None:
            sessions.append(AgentSession(pid=pid, name=name, repo_path=repo))
    return sessions


def _proc_cwd(pid: int) -> Path | None:
    """Return process cwd. Linux uses /proc, macOS/BSD uses lsof."""
    if platform.system() == "Linux":
        try:
            return Path(os.readlink(f"/proc/{pid}/cwd"))
        except (FileNotFoundError, PermissionError, OSError):
            return None
    raw = _run(["lsof", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=2.0)
    return parse_lsof_cwd(raw)
