"""Pure logic for goldfish: dataclasses, parsers, formatters, sort.

No subprocess, no filesystem reads, no network. Everything in this module
takes strings/data in and returns data out, so it is trivial to unit test.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# --- Domain types ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class GithubInfo:
    name: str
    pushed_at: datetime | None
    open_pr_count: int = 0


@dataclass(frozen=True, slots=True)
class LocalInfo:
    path: Path
    is_dirty: bool
    ahead: int
    behind: int
    branch: str
    last_commit_at: datetime | None
    next_task: str | None


@dataclass(frozen=True, slots=True)
class AgentSession:
    pid: int
    name: str
    repo_path: Path


@dataclass(frozen=True, slots=True)
class RepoRow:
    name: str
    github: GithubInfo | None
    local: LocalInfo | None
    agents: tuple[AgentSession, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GitDirtyState:
    branch: str
    is_dirty: bool
    ahead: int
    behind: int


# --- Parsers -----------------------------------------------------------------

_TODO_LINE = re.compile(r"^\s*-\s*\[\s\]\s*(.+?)\s*$")
_STRUCK = re.compile(r"^~~.*~~")


def parse_todo_plan(text: str) -> str | None:
    """Return the first unchecked task from a TODO_PLAN.md, or None."""
    for raw in text.splitlines():
        m = _TODO_LINE.match(raw)
        if not m:
            continue
        task = m.group(1).strip()
        if _STRUCK.match(task):
            continue
        return task
    return None


def parse_gh_repo_list(raw: str) -> list[GithubInfo]:
    """Parse `gh repo list --json nameWithOwner,pushedAt,isArchived` output."""
    data = json.loads(raw)
    out: list[GithubInfo] = []
    for entry in data:
        if entry.get("isArchived"):
            continue
        pushed = entry.get("pushedAt")
        pushed_dt = _parse_iso(pushed) if pushed else None
        out.append(GithubInfo(name=entry["nameWithOwner"], pushed_at=pushed_dt))
    return out


def _parse_iso(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp (accepts trailing Z)."""
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


_BRANCH_LINE = re.compile(
    r"^##\s+(?P<branch>[^.\s]+)"
    r"(?:\.\.\.\S+)?"
    r"(?:\s+\[(?P<tracking>[^\]]+)\])?"
)
_NO_COMMITS = re.compile(r"^##\s+No commits yet on\s+(?P<branch>\S+)")


def parse_git_porcelain(output: str) -> GitDirtyState:
    """Parse `git status --porcelain=v1 -b` output into a GitDirtyState."""
    lines = output.splitlines()
    branch = ""
    ahead = 0
    behind = 0
    file_lines = []
    for line in lines:
        if line.startswith("##"):
            m_no = _NO_COMMITS.match(line)
            if m_no:
                branch = m_no.group("branch")
                continue
            m = _BRANCH_LINE.match(line)
            if m:
                branch = m.group("branch")
                tracking = m.group("tracking") or ""
                ahead = _extract_count(tracking, "ahead")
                behind = _extract_count(tracking, "behind")
        else:
            file_lines.append(line)
    return GitDirtyState(
        branch=branch,
        is_dirty=any(file_lines),
        ahead=ahead,
        behind=behind,
    )


def _extract_count(tracking: str, key: str) -> int:
    m = re.search(rf"{key} (\d+)", tracking)
    return int(m.group(1)) if m else 0


def parse_ps(output: str, *, known: set[str]) -> list[tuple[int, str]]:
    """Parse `ps -axo pid=,comm=` output. Return (pid, basename) for known names."""
    out: list[tuple[int, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, comm = parts
        if not pid_str.isdigit():
            continue
        name = comm.rsplit("/", 1)[-1]
        if name in known:
            out.append((int(pid_str), name))
    return out


def parse_lsof_cwd(output: str) -> Path | None:
    """Parse `lsof -p PID -d cwd -Fn` output. Returns the path or None."""
    for line in output.splitlines():
        if line.startswith("n"):
            return Path(line[1:])
    return None


# --- Logic -------------------------------------------------------------------

def enclosing_repo(path: Path, repos: Iterable[Path]) -> Path | None:
    """Return the deepest known repo path that contains `path`, or None."""
    best: Path | None = None
    for repo in repos:
        try:
            path.relative_to(repo)
        except ValueError:
            continue
        if best is None or len(repo.parts) > len(best.parts):
            best = repo
    return best


def latest_activity(row: RepoRow, *, now: datetime | None = None) -> datetime | None:
    """Most-recent activity signal across github, local, and running agents."""
    candidates: list[datetime] = []
    if row.github and row.github.pushed_at:
        candidates.append(row.github.pushed_at)
    if row.local and row.local.last_commit_at:
        candidates.append(row.local.last_commit_at)
    if row.agents:
        candidates.append(now or datetime.now(timezone.utc))
    if not candidates:
        return None
    return max(candidates)


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def sort_rows(rows: Iterable[RepoRow], *, now: datetime | None = None) -> list[RepoRow]:
    """Sort rows by `latest_activity` descending; rows with no signal go last."""
    def key(r: RepoRow) -> datetime:
        return latest_activity(r, now=now) or _EPOCH
    return sorted(rows, key=key, reverse=True)


# --- Verbose process listing (G6) --------------------------------------------

def format_processes(sessions: Iterable[AgentSession]) -> str:
    """Render processes-in-tracked-repos as a per-repo block. Empty input -> ''."""
    sessions = list(sessions)
    if not sessions:
        return ""
    by_repo: dict[Path, list[AgentSession]] = {}
    for s in sessions:
        by_repo.setdefault(s.repo_path, []).append(s)
    lines = ["PROCESSES IN TRACKED REPOS"]
    for repo in sorted(by_repo):
        lines.append(f"  {repo}")
        for s in sorted(by_repo[repo], key=lambda x: x.pid):
            lines.append(f"    {s.pid:>7}  {s.name}")
    return "\n".join(lines)


# --- Org filter (G7) ---------------------------------------------------------

def apply_org_filter(
    rows: Iterable[RepoRow],
    *,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> list[RepoRow]:
    """Filter rows by owner. include='' means no allow-list; exclude wins ties."""
    excluded = set(exclude)
    included = set(include)
    out: list[RepoRow] = []
    for row in rows:
        owner = row.name.split("/", 1)[0] if "/" in row.name else ""
        if owner in excluded:
            continue
        if included and owner not in included:
            continue
        out.append(row)
    return out


# --- JSON serialization (G5) -------------------------------------------------

def rows_to_json(rows: Iterable[RepoRow]) -> str:
    """Render rows as a JSON array. Stable shape for piping into other tools."""
    return json.dumps([_row_to_jsonable(r) for r in rows], indent=2, sort_keys=True)


def _row_to_jsonable(r: RepoRow) -> dict:
    return {
        "name": r.name,
        "github": _github_to_jsonable(r.github),
        "local": _local_to_jsonable(r.local),
        "agents": [
            {"pid": a.pid, "name": a.name, "repo_path": str(a.repo_path)}
            for a in r.agents
        ],
    }


def _github_to_jsonable(g: GithubInfo | None) -> dict | None:
    if g is None:
        return None
    return {
        "name": g.name,
        "pushed_at": g.pushed_at.isoformat() if g.pushed_at else None,
        "open_pr_count": g.open_pr_count,
    }


def _local_to_jsonable(l: LocalInfo | None) -> dict | None:
    if l is None:
        return None
    return {
        "path": str(l.path),
        "is_dirty": l.is_dirty,
        "ahead": l.ahead,
        "behind": l.behind,
        "branch": l.branch,
        "last_commit_at": l.last_commit_at.isoformat() if l.last_commit_at else None,
        "next_task": l.next_task,
    }


# --- Formatter ---------------------------------------------------------------

_HEADERS = ("REPO", "PRS", "DIRTY", "AHEAD", "BRANCH", "AGENTS", "NEXT")


def format_table(rows: Iterable[RepoRow], *, max_width: int = 200) -> str:
    """Render rows as a fixed-column ASCII table. Truncates to max_width per line."""
    rendered = [_HEADERS]
    for r in rows:
        rendered.append(_format_row(r))

    widths = [max(len(c) for c in col) for col in zip(*rendered)]
    widths = list(widths)

    next_col = _HEADERS.index("NEXT")
    fixed = sum(widths[:next_col]) + 2 * next_col
    widths[next_col] = max(4, max_width - fixed - 2)

    lines = []
    for row in rendered:
        cells = [_pad_or_trunc(cell, widths[i]) for i, cell in enumerate(row)]
        line = "  ".join(cells).rstrip()
        if len(line) > max_width:
            line = line[: max_width - 1] + "…"
        lines.append(line)
    return "\n".join(lines)


def _format_row(r: RepoRow) -> tuple[str, ...]:
    prs = str(r.github.open_pr_count) if r.github else "—"
    if r.local:
        dirty = "*" if r.local.is_dirty else "."
        ahead = str(r.local.ahead) if r.local.ahead else "."
        branch = r.local.branch or "—"
        next_task = r.local.next_task or "—"
    else:
        dirty = "—"
        ahead = "—"
        branch = "—"
        next_task = "—"
    agents = ",".join(sorted({a.name for a in r.agents})) or "—"
    return (r.name, prs, dirty, ahead, branch, agents, next_task)


def _pad_or_trunc(text: str, width: int) -> str:
    if len(text) > width:
        return text[: width - 1] + "…"
    return text.ljust(width)
