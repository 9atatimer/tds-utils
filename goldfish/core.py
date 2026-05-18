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


# --- LLM output cleanup (G2) -------------------------------------------------

LLM_LINE_MAX = 200


def first_meaningful_line(raw: str) -> str | None:
    """Return the first non-empty line, stripped of leading bullets/quotes.

    Bounded to LLM_LINE_MAX chars so a chatty model can't blow up the table.
    """
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        for prefix in ("- ", "* ", "• "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
            cleaned = cleaned[1:-1]
        if len(cleaned) > LLM_LINE_MAX:
            cleaned = cleaned[:LLM_LINE_MAX]
        return cleaned or None
    return None


# --- Clones cache (G3) -------------------------------------------------------

CLONES_CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class ClonesCache:
    saved_at: datetime
    clones: dict[str, Path]


def serialize_clones_cache(clones: dict[str, Path], *, saved_at: datetime) -> str:
    """Render the clones map as JSON for `$XDG_CACHE_HOME/goldfish/clones.json`."""
    return json.dumps({
        "version": CLONES_CACHE_VERSION,
        "saved_at": saved_at.isoformat(),
        "clones": {name: str(path) for name, path in sorted(clones.items())},
    }, indent=2)


def parse_clones_cache(text: str) -> ClonesCache | None:
    """Parse a clones cache file. Returns None if malformed or wrong version."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != CLONES_CACHE_VERSION:
        return None
    raw_saved = data.get("saved_at")
    raw_clones = data.get("clones")
    if not isinstance(raw_saved, str) or not isinstance(raw_clones, dict):
        return None
    try:
        saved = _parse_iso(raw_saved)
    except ValueError:
        return None
    clones: dict[str, Path] = {}
    for name, path in raw_clones.items():
        if isinstance(name, str) and isinstance(path, str):
            clones[name] = Path(path)
    return ClonesCache(saved_at=saved, clones=clones)


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


# --- Blacklist ---------------------------------------------------------------

BLACKLIST_VERSION = 1


def serialize_blacklist(names: Iterable[str]) -> str:
    """Render the blacklist as JSON for the user's config file."""
    return json.dumps({
        "version": BLACKLIST_VERSION,
        "names": sorted(set(names)),
    }, indent=2)


def parse_blacklist(text: str) -> frozenset[str]:
    """Parse a blacklist file. Returns an empty frozenset on any problem."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return frozenset()
    if not isinstance(data, dict) or data.get("version") != BLACKLIST_VERSION:
        return frozenset()
    raw = data.get("names")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(n for n in raw if isinstance(n, str))


def apply_blacklist(
    rows: Iterable[RepoRow],
    *,
    blacklist: frozenset[str],
) -> list[RepoRow]:
    """Drop rows whose name appears in the blacklist."""
    if not blacklist:
        return list(rows)
    return [r for r in rows if r.name not in blacklist]


# --- Marker state (fzf-driven blacklist picker) ------------------------------

_MARKER_ON = "[x] "
_MARKER_OFF = "[ ] "


def format_marker_state(
    names: Iterable[str],
    *,
    selected: Iterable[str],
) -> str:
    """Render `names` as marker-prefixed lines, preserving input order.

    Selected names get '[x] '; the rest get '[ ] '. Feeds the fzf picker.
    """
    sel = set(selected)
    return "\n".join(
        (_MARKER_ON if n in sel else _MARKER_OFF) + n for n in names
    )


def parse_marker_state(text: str) -> frozenset[str]:
    """Recover the set of checked names from a marker-state string.

    Only lines starting with '[x] ' contribute. Anything else is dropped.
    """
    return frozenset(
        line[len(_MARKER_ON):]
        for line in text.splitlines()
        if line.startswith(_MARKER_ON)
    )


def toggle_marker_line(line: str) -> str:
    """Flip the marker prefix on a single line. No-op on unrecognized lines."""
    if line.startswith(_MARKER_ON):
        return _MARKER_OFF + line[len(_MARKER_ON):]
    if line.startswith(_MARKER_OFF):
        return _MARKER_ON + line[len(_MARKER_OFF):]
    return line


# --- Actionability filter ----------------------------------------------------

def is_actionable(row: RepoRow) -> bool:
    """True if the row has any open PR, dirty tree, unpushed commits, agent, or NEXT task."""
    if row.github is not None and row.github.open_pr_count > 0:
        return True
    if row.local is not None and (
        row.local.is_dirty or row.local.ahead > 0 or row.local.next_task
    ):
        return True
    if row.agents:
        return True
    return False


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
_HEADERS_WITH_BL = ("REPO", "PRS", "DIRTY", "AHEAD", "BRANCH", "AGENTS", "BL", "NEXT")


def format_table(
    rows: Iterable[RepoRow],
    *,
    max_width: int = 200,
    blacklisted: frozenset[str] = frozenset(),
) -> str:
    """Render rows as a fixed-column ASCII table. Truncates to max_width per line.

    When `blacklisted` is non-empty, a BL column is inserted before NEXT marking
    rows whose name is in the set with `*`.
    """
    show_bl = bool(blacklisted)
    headers = _HEADERS_WITH_BL if show_bl else _HEADERS
    rendered = [headers]
    for r in rows:
        rendered.append(_format_row(r, blacklisted=blacklisted, show_bl=show_bl))

    widths = [max(len(c) for c in col) for col in zip(*rendered)]
    widths = list(widths)

    next_col = headers.index("NEXT")
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


def _format_row(
    r: RepoRow,
    *,
    blacklisted: frozenset[str] = frozenset(),
    show_bl: bool = False,
) -> tuple[str, ...]:
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
    if show_bl:
        bl = "*" if r.name in blacklisted else "."
        return (r.name, prs, dirty, ahead, branch, agents, bl, next_task)
    return (r.name, prs, dirty, ahead, branch, agents, next_task)


def _pad_or_trunc(text: str, width: int) -> str:
    if len(text) > width:
        return text[: width - 1] + "…"
    return text.ljust(width)
