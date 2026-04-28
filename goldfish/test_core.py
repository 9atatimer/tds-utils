"""Unit tests for goldfish.core.

All tests are pure: no subprocess, no filesystem, no network.
They exercise parsers, formatters, and sort logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core import (
    AgentSession,
    GithubInfo,
    LocalInfo,
    RepoRow,
    enclosing_repo,
    format_table,
    latest_activity,
    parse_git_porcelain,
    parse_gh_repo_list,
    parse_lsof_cwd,
    parse_ps,
    parse_todo_plan,
    sort_rows,
)


# --- parse_todo_plan ---------------------------------------------------------

def test_parse_todo_plan_first_unchecked() -> None:
    """Given a TODO_PLAN with checked and unchecked items, returns the first unchecked."""
    text = (
        "# Plan\n"
        "- [x] done thing\n"
        "- [ ] write goldfish\n"
        "- [ ] ship goldfish\n"
    )
    assert parse_todo_plan(text) == "write goldfish"


def test_parse_todo_plan_no_unchecked_returns_none() -> None:
    """Given a TODO_PLAN with everything checked, returns None."""
    text = "- [x] one\n- [x] two\n"
    assert parse_todo_plan(text) is None


def test_parse_todo_plan_handles_indented_and_nested() -> None:
    """Given an indented unchecked item, it is still considered."""
    text = "## Active\n  - [ ] indented task\n"
    assert parse_todo_plan(text) == "indented task"


def test_parse_todo_plan_empty_string_returns_none() -> None:
    """Given empty input, returns None."""
    assert parse_todo_plan("") is None


def test_parse_todo_plan_skips_struck_through() -> None:
    """Given a struck-through unchecked item, skip it."""
    text = "- [ ] ~~old idea~~ (superseded)\n- [ ] real task\n"
    assert parse_todo_plan(text) == "real task"


# --- parse_gh_repo_list ------------------------------------------------------

def test_parse_gh_repo_list_basic() -> None:
    """Given gh repo list JSON, extracts name and pushedAt."""
    raw = (
        '[{"nameWithOwner":"todd/foo","pushedAt":"2026-04-20T10:00:00Z","isArchived":false},'
        '{"nameWithOwner":"todd/bar","pushedAt":"2026-04-15T08:00:00Z","isArchived":false}]'
    )
    out = parse_gh_repo_list(raw)
    assert len(out) == 2
    assert out[0].name == "todd/foo"
    assert out[0].pushed_at == datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)


def test_parse_gh_repo_list_skips_archived() -> None:
    """Given an archived repo in the JSON, exclude it."""
    raw = (
        '[{"nameWithOwner":"todd/foo","pushedAt":"2026-04-20T10:00:00Z","isArchived":true},'
        '{"nameWithOwner":"todd/bar","pushedAt":"2026-04-15T08:00:00Z","isArchived":false}]'
    )
    out = parse_gh_repo_list(raw)
    assert [r.name for r in out] == ["todd/bar"]


def test_parse_gh_repo_list_handles_null_pushed_at() -> None:
    """Given a repo with null pushedAt, store None."""
    raw = '[{"nameWithOwner":"todd/empty","pushedAt":null,"isArchived":false}]'
    out = parse_gh_repo_list(raw)
    assert out[0].pushed_at is None


# --- parse_git_porcelain -----------------------------------------------------

def test_parse_git_porcelain_clean() -> None:
    """Given an empty porcelain output, the tree is clean."""
    state = parse_git_porcelain("## main...origin/main\n")
    assert state.is_dirty is False
    assert state.branch == "main"


def test_parse_git_porcelain_dirty() -> None:
    """Given porcelain with file changes, the tree is dirty."""
    out = "## main...origin/main\n M file.txt\n?? newfile\n"
    state = parse_git_porcelain(out)
    assert state.is_dirty is True


def test_parse_git_porcelain_ahead_behind() -> None:
    """Given branch line with [ahead N, behind M], capture both."""
    out = "## feature...origin/feature [ahead 3, behind 1]\n"
    state = parse_git_porcelain(out)
    assert state.ahead == 3
    assert state.behind == 1


def test_parse_git_porcelain_only_ahead() -> None:
    """Given branch line with only ahead, behind is 0."""
    out = "## main...origin/main [ahead 5]\n"
    state = parse_git_porcelain(out)
    assert state.ahead == 5
    assert state.behind == 0


def test_parse_git_porcelain_no_upstream() -> None:
    """Given branch with no upstream, both ahead and behind are 0."""
    out = "## feature\n"
    state = parse_git_porcelain(out)
    assert state.ahead == 0
    assert state.behind == 0
    assert state.branch == "feature"


def test_parse_git_porcelain_no_commits_yet() -> None:
    """Given a freshly-init'd repo (no commits), branch is captured correctly."""
    out = "## No commits yet on master\n?? a.txt\n"
    state = parse_git_porcelain(out)
    assert state.branch == "master"
    assert state.is_dirty is True


def test_parse_git_porcelain_detached_head() -> None:
    """Given a detached HEAD checkout, branch reads as the literal git label."""
    out = "## HEAD (no branch)\n"
    state = parse_git_porcelain(out)
    assert state.branch == "HEAD"


# --- parse_ps ----------------------------------------------------------------

def test_parse_ps_filters_to_known_agents() -> None:
    """Given ps output, returns only matching agents."""
    out = (
        "  123 bash\n"
        "  456 claude\n"
        "  789 vim\n"
        " 1011 codex\n"
    )
    agents = parse_ps(out, known={"claude", "codex", "gemini"})
    assert sorted((p, n) for p, n in agents) == [(456, "claude"), (1011, "codex")]


def test_parse_ps_handles_full_path_comm() -> None:
    """Given ps output with full path in comm, match by basename."""
    out = "  123 /opt/node22/bin/claude\n  456 /usr/local/bin/aider\n"
    agents = parse_ps(out, known={"claude", "aider"})
    assert sorted(agents) == [(123, "claude"), (456, "aider")]


def test_parse_ps_ignores_unknown() -> None:
    """Given ps output with no known agents, returns empty list."""
    assert parse_ps("  1 init\n  2 sshd\n", known={"claude"}) == []


# --- parse_lsof_cwd ----------------------------------------------------------

def test_parse_lsof_cwd_extracts_path() -> None:
    """Given lsof -Fn output, returns the cwd path."""
    out = "p1234\nfcwd\nn/home/user/proj\n"
    assert parse_lsof_cwd(out) == Path("/home/user/proj")


def test_parse_lsof_cwd_no_cwd_returns_none() -> None:
    """Given lsof output with no cwd field, returns None."""
    assert parse_lsof_cwd("p1234\n") is None


# --- enclosing_repo ----------------------------------------------------------

def test_enclosing_repo_direct_match() -> None:
    """Given a path that is exactly a known repo, returns it."""
    repos = {Path("/home/u/proj"), Path("/home/u/other")}
    assert enclosing_repo(Path("/home/u/proj"), repos) == Path("/home/u/proj")


def test_enclosing_repo_subdirectory() -> None:
    """Given a path under a known repo, returns the repo path."""
    repos = {Path("/home/u/proj")}
    assert enclosing_repo(Path("/home/u/proj/src/x.py"), repos) == Path("/home/u/proj")


def test_enclosing_repo_no_match() -> None:
    """Given a path outside all known repos, returns None."""
    repos = {Path("/home/u/proj")}
    assert enclosing_repo(Path("/tmp/elsewhere"), repos) is None


def test_enclosing_repo_picks_deepest() -> None:
    """Given nested known repos, returns the deepest (most specific) match."""
    repos = {Path("/home/u"), Path("/home/u/proj")}
    assert enclosing_repo(Path("/home/u/proj/src"), repos) == Path("/home/u/proj")


# --- latest_activity ---------------------------------------------------------

def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_latest_activity_picks_max_of_signals() -> None:
    """Given a row with github push older than local commit, picks local commit."""
    row = RepoRow(
        name="todd/foo",
        github=GithubInfo(name="todd/foo", pushed_at=_utc(2026, 4, 1), open_pr_count=0),
        local=LocalInfo(
            path=Path("/x"), is_dirty=False, ahead=0, behind=0,
            branch="main", last_commit_at=_utc(2026, 4, 20), next_task=None,
        ),
        agents=(),
    )
    assert latest_activity(row) == _utc(2026, 4, 20)


def test_latest_activity_running_agent_pins_to_now() -> None:
    """Given a running agent, latest_activity is at least as recent as both signals."""
    row = RepoRow(
        name="todd/foo",
        github=GithubInfo(name="todd/foo", pushed_at=_utc(2020, 1, 1), open_pr_count=0),
        local=None,
        agents=(AgentSession(pid=1, name="claude", repo_path=Path("/x")),),
    )
    now = datetime.now(timezone.utc)
    result = latest_activity(row, now=now)
    assert result == now


def test_latest_activity_no_signals_returns_none() -> None:
    """Given no signals, returns None."""
    row = RepoRow(name="todd/empty", github=None, local=None, agents=())
    assert latest_activity(row) is None


# --- sort_rows ---------------------------------------------------------------

def test_sort_rows_descending_by_activity() -> None:
    """Given rows with varying activity, sorted descending puts newest first."""
    a = RepoRow(
        name="a",
        github=GithubInfo(name="a", pushed_at=_utc(2026, 4, 1), open_pr_count=0),
        local=None, agents=(),
    )
    b = RepoRow(
        name="b",
        github=GithubInfo(name="b", pushed_at=_utc(2026, 4, 25), open_pr_count=0),
        local=None, agents=(),
    )
    c = RepoRow(name="c", github=None, local=None, agents=())
    out = sort_rows([a, b, c])
    assert [r.name for r in out] == ["b", "a", "c"]


# --- format_table ------------------------------------------------------------

def test_format_table_header_present() -> None:
    """Given any rows, output starts with the header row."""
    rows = [RepoRow(name="todd/foo", github=None, local=None, agents=())]
    table = format_table(rows)
    first = table.splitlines()[0]
    assert "REPO" in first
    assert "PRS" in first
    assert "AGENTS" in first


def test_format_table_renders_repo_name() -> None:
    """Given a row, the repo name appears in the rendered table."""
    rows = [RepoRow(name="todd/foo", github=None, local=None, agents=())]
    assert "todd/foo" in format_table(rows)


def test_format_table_dirty_marker() -> None:
    """Given a dirty local repo, the row contains the dirty marker."""
    rows = [RepoRow(
        name="todd/foo",
        github=None,
        local=LocalInfo(
            path=Path("/x"), is_dirty=True, ahead=2, behind=0,
            branch="main", last_commit_at=None, next_task=None,
        ),
        agents=(),
    )]
    table = format_table(rows)
    line = [l for l in table.splitlines() if "todd/foo" in l][0]
    assert "*" in line


def test_format_table_agents_listed() -> None:
    """Given agents on a row, their names appear comma-separated."""
    rows = [RepoRow(
        name="todd/foo",
        github=None,
        local=None,
        agents=(
            AgentSession(pid=1, name="claude", repo_path=Path("/x")),
            AgentSession(pid=2, name="codex", repo_path=Path("/x")),
        ),
    )]
    table = format_table(rows)
    line = [l for l in table.splitlines() if "todd/foo" in l][0]
    assert "claude" in line and "codex" in line


def test_format_table_next_task_truncated() -> None:
    """Given a long next task, the field is truncated to fit the column."""
    long_task = "x" * 200
    rows = [RepoRow(
        name="todd/foo",
        github=None,
        local=LocalInfo(
            path=Path("/x"), is_dirty=False, ahead=0, behind=0,
            branch="main", last_commit_at=None, next_task=long_task,
        ),
        agents=(),
    )]
    table = format_table(rows, max_width=120)
    for line in table.splitlines():
        assert len(line) <= 120
