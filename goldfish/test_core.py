"""Unit tests for goldfish.core.

All tests are pure: no subprocess, no filesystem, no network.
They exercise parsers, formatters, and sort logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core import (
    AgentSession,
    CommitSummary,
    GithubInfo,
    LocalInfo,
    PRSummary,
    RepoRow,
    ZoomData,
    apply_blacklist,
    apply_org_filter,
    enclosing_repo,
    first_meaningful_line,
    format_marker_state,
    format_processes,
    format_table,
    format_zoom,
    is_actionable,
    latest_activity,
    parse_blacklist,
    parse_clones_cache,
    parse_git_porcelain,
    parse_gh_repo_list,
    parse_lsof_cwd,
    parse_marker_state,
    parse_ps,
    parse_todo_plan,
    parse_todo_plan_all,
    resolve_repo_name,
    rows_to_json,
    serialize_blacklist,
    serialize_clones_cache,
    sort_rows,
    toggle_marker_line,
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


# --- first_meaningful_line (G2) ----------------------------------------------

def test_first_meaningful_line_returns_first_nonempty() -> None:
    """Given output with leading blank lines, returns the first non-empty line."""
    raw = "\n\n  \nactual content here\nignored\n"
    assert first_meaningful_line(raw) == "actual content here"


def test_first_meaningful_line_strips_quotes_and_bullets() -> None:
    """Given LLM-style output with quotes / bullets, those are stripped."""
    assert first_meaningful_line('"Wire up retry on 429"') == "Wire up retry on 429"
    assert first_meaningful_line("- Wire up retry") == "Wire up retry"
    assert first_meaningful_line("* Wire up retry") == "Wire up retry"


def test_first_meaningful_line_empty_input_returns_none() -> None:
    """Given empty/whitespace input, returns None."""
    assert first_meaningful_line("") is None
    assert first_meaningful_line("   \n\n") is None


def test_first_meaningful_line_truncates_long_output() -> None:
    """Given a long line, output is bounded so it fits the table column."""
    long = "x" * 500
    assert len(first_meaningful_line(long)) <= 200


# --- clones cache (G3) -------------------------------------------------------

def test_serialize_clones_cache_round_trips() -> None:
    """Given a clones map, serialize then parse returns the same map."""
    clones = {"a/x": Path("/r/a/x"), "b/y": Path("/r/b/y")}
    text = serialize_clones_cache(clones, saved_at=_utc(2026, 4, 28))
    cache = parse_clones_cache(text)
    assert cache.clones == clones
    assert cache.saved_at == _utc(2026, 4, 28)


def test_parse_clones_cache_handles_unknown_version_gracefully() -> None:
    """Given a future-version cache file, returns None instead of raising."""
    bad = '{"version": 99, "clones": {"a/x": "/r/a/x"}}'
    assert parse_clones_cache(bad) is None


def test_parse_clones_cache_handles_garbage() -> None:
    """Given non-JSON input, returns None instead of raising."""
    assert parse_clones_cache("not json at all") is None


def test_parse_clones_cache_empty_clones_map() -> None:
    """Given a valid cache with no clones, returns an empty map."""
    text = serialize_clones_cache({}, saved_at=_utc(2026, 4, 1))
    cache = parse_clones_cache(text)
    assert cache.clones == {}


# --- format_processes (G6) ---------------------------------------------------

def test_format_processes_empty_list_returns_empty_string() -> None:
    """Given no sessions, returns empty string (no header)."""
    assert format_processes([]) == ""


def test_format_processes_groups_by_repo() -> None:
    """Given sessions across two repos, output groups them under each repo path."""
    sessions = [
        AgentSession(pid=1, name="claude", repo_path=Path("/r/a")),
        AgentSession(pid=2, name="vim", repo_path=Path("/r/b")),
        AgentSession(pid=3, name="bash", repo_path=Path("/r/a")),
    ]
    out = format_processes(sessions)
    assert "/r/a" in out and "/r/b" in out
    a_block_start = out.index("/r/a")
    b_block_start = out.index("/r/b")
    a_block = out[a_block_start:b_block_start] if a_block_start < b_block_start else out[a_block_start:]
    assert "claude" in a_block and "bash" in a_block


def test_format_processes_includes_pid_and_name() -> None:
    """Given a session, both pid and name appear in the output."""
    sessions = [AgentSession(pid=4242, name="codex", repo_path=Path("/r/x"))]
    out = format_processes(sessions)
    assert "4242" in out and "codex" in out


# --- apply_org_filter (G7) ---------------------------------------------------

def _row(name: str) -> RepoRow:
    return RepoRow(name=name, github=None, local=None, agents=())


def test_apply_org_filter_no_filters_passes_everything() -> None:
    """Given no include/exclude, every row survives."""
    rows = [_row("a/x"), _row("b/y")]
    out = apply_org_filter(rows, include=(), exclude=())
    assert [r.name for r in out] == ["a/x", "b/y"]


def test_apply_org_filter_include_keeps_only_listed_orgs() -> None:
    """Given include=('a',), rows whose owner is 'a' survive; others drop."""
    rows = [_row("a/x"), _row("b/y"), _row("a/z")]
    out = apply_org_filter(rows, include=("a",), exclude=())
    assert sorted(r.name for r in out) == ["a/x", "a/z"]


def test_apply_org_filter_exclude_drops_listed_orgs() -> None:
    """Given exclude=('b',), rows whose owner is 'b' drop; others survive."""
    rows = [_row("a/x"), _row("b/y"), _row("c/z")]
    out = apply_org_filter(rows, include=(), exclude=("b",))
    assert sorted(r.name for r in out) == ["a/x", "c/z"]


def test_apply_org_filter_exclude_wins_over_include() -> None:
    """Given a/x in both include and exclude, exclude wins."""
    rows = [_row("a/x"), _row("a/y")]
    out = apply_org_filter(rows, include=("a",), exclude=("a",))
    assert out == []


def test_apply_org_filter_handles_unowned_names() -> None:
    """Given a row with no owner/ prefix (malformed), include filter rejects it."""
    rows = [_row("noowner")]
    out = apply_org_filter(rows, include=("a",), exclude=())
    assert out == []


# --- rows_to_json (G5) -------------------------------------------------------

def test_rows_to_json_emits_valid_json() -> None:
    """Given any rows, output parses as JSON."""
    import json
    rows = [_row("a/x")]
    parsed = json.loads(rows_to_json(rows))
    assert isinstance(parsed, list) and parsed[0]["name"] == "a/x"


def test_rows_to_json_serializes_all_fields() -> None:
    """Given a fully-populated row, JSON contains every column."""
    import json
    row = RepoRow(
        name="a/x",
        github=GithubInfo(name="a/x", pushed_at=_utc(2026, 4, 1), open_pr_count=2),
        local=LocalInfo(
            path=Path("/x"), is_dirty=True, ahead=3, behind=1,
            branch="main", last_commit_at=_utc(2026, 4, 20),
            next_task="do the thing",
        ),
        agents=(AgentSession(pid=1, name="claude", repo_path=Path("/x")),),
    )
    parsed = json.loads(rows_to_json([row]))
    entry = parsed[0]
    assert entry["github"]["open_pr_count"] == 2
    assert entry["local"]["is_dirty"] is True
    assert entry["local"]["next_task"] == "do the thing"
    assert entry["agents"][0]["name"] == "claude"


def test_rows_to_json_handles_missing_github_and_local() -> None:
    """Given a row with no github or local info, those fields are null."""
    import json
    parsed = json.loads(rows_to_json([_row("a/x")]))
    assert parsed[0]["github"] is None
    assert parsed[0]["local"] is None
    assert parsed[0]["agents"] == []


# --- is_actionable -----------------------------------------------------------

def _clean_local(**overrides) -> LocalInfo:
    """Build a clean (no signals) LocalInfo for actionability tests."""
    defaults = dict(
        path=Path("/x"), is_dirty=False, ahead=0, behind=0,
        branch="main", last_commit_at=None, next_task=None,
    )
    defaults.update(overrides)
    return LocalInfo(**defaults)


def test_is_actionable_open_pr_counts_as_actionable() -> None:
    """Given a row with open PRs, it is actionable."""
    row = RepoRow(
        name="a/x",
        github=GithubInfo(name="a/x", pushed_at=None, open_pr_count=1),
        local=_clean_local(),
        agents=(),
    )
    assert is_actionable(row) is True


def test_is_actionable_dirty_tree_counts_as_actionable() -> None:
    """Given a dirty working tree, the row is actionable."""
    row = RepoRow(
        name="a/x", github=None,
        local=_clean_local(is_dirty=True), agents=(),
    )
    assert is_actionable(row) is True


def test_is_actionable_ahead_counts_as_actionable() -> None:
    """Given unpushed commits (ahead > 0), the row is actionable."""
    row = RepoRow(
        name="a/x", github=None,
        local=_clean_local(ahead=2), agents=(),
    )
    assert is_actionable(row) is True


def test_is_actionable_running_agent_counts_as_actionable() -> None:
    """Given a running agent, the row is actionable."""
    row = RepoRow(
        name="a/x", github=None, local=_clean_local(),
        agents=(AgentSession(pid=1, name="claude", repo_path=Path("/x")),),
    )
    assert is_actionable(row) is True


def test_is_actionable_next_task_counts_as_actionable() -> None:
    """Given a NEXT task in the local row, it is actionable."""
    row = RepoRow(
        name="a/x", github=None,
        local=_clean_local(next_task="do the thing"), agents=(),
    )
    assert is_actionable(row) is True


def test_is_actionable_clean_clone_with_zero_prs_is_idle() -> None:
    """Given a clean clone, no PRs, no agents, no task — the row is idle."""
    row = RepoRow(
        name="a/x",
        github=GithubInfo(name="a/x", pushed_at=None, open_pr_count=0),
        local=_clean_local(),
        agents=(),
    )
    assert is_actionable(row) is False


def test_is_actionable_orphan_github_row_is_idle() -> None:
    """Given a cloud-only row with no PRs and no other signals, it is idle."""
    row = RepoRow(
        name="a/x",
        github=GithubInfo(name="a/x", pushed_at=None, open_pr_count=0),
        local=None, agents=(),
    )
    assert is_actionable(row) is False


def test_is_actionable_empty_row_is_idle() -> None:
    """Given a row with no github, no local, no agents, it is idle."""
    row = RepoRow(name="a/x", github=None, local=None, agents=())
    assert is_actionable(row) is False


# --- blacklist parse/serialize -----------------------------------------------

def test_serialize_blacklist_round_trips() -> None:
    """Given a set of names, serialize then parse returns the same set."""
    names = frozenset({"a/x", "b/y"})
    text = serialize_blacklist(names)
    assert parse_blacklist(text) == names


def test_parse_blacklist_empty_file_returns_empty_set() -> None:
    """Given an empty/missing payload, parse returns an empty frozenset."""
    text = serialize_blacklist(frozenset())
    assert parse_blacklist(text) == frozenset()


def test_parse_blacklist_handles_garbage() -> None:
    """Given non-JSON input, returns empty frozenset (no crash)."""
    assert parse_blacklist("not json") == frozenset()
    assert parse_blacklist("") == frozenset()


def test_parse_blacklist_handles_unknown_version() -> None:
    """Given a future-version file, returns empty frozenset."""
    assert parse_blacklist('{"version": 99, "names": ["a/x"]}') == frozenset()


def test_parse_blacklist_ignores_non_string_entries() -> None:
    """Given a names array with non-string entries, those are dropped."""
    text = '{"version": 1, "names": ["a/x", 42, null, "b/y"]}'
    assert parse_blacklist(text) == frozenset({"a/x", "b/y"})


# --- apply_blacklist ---------------------------------------------------------

def test_apply_blacklist_drops_blacklisted_rows() -> None:
    """Given a blacklist, rows whose name is in it are removed."""
    rows = [_row("a/x"), _row("b/y"), _row("c/z")]
    out = apply_blacklist(rows, blacklist=frozenset({"b/y"}))
    assert [r.name for r in out] == ["a/x", "c/z"]


def test_apply_blacklist_empty_set_passes_everything() -> None:
    """Given an empty blacklist, no rows are dropped."""
    rows = [_row("a/x"), _row("b/y")]
    assert apply_blacklist(rows, blacklist=frozenset()) == rows


def test_apply_blacklist_unknown_names_have_no_effect() -> None:
    """Given a blacklist with names not in the rows, nothing changes."""
    rows = [_row("a/x")]
    assert apply_blacklist(rows, blacklist=frozenset({"nothere/repo"})) == rows


# --- format_table BL column --------------------------------------------------

def test_format_table_no_bl_column_by_default() -> None:
    """Given no blacklisted set, BL column is absent (back-compat)."""
    rows = [_row("a/x")]
    header = format_table(rows).splitlines()[0]
    assert "BL" not in header.split()


def test_format_table_bl_column_when_blacklisted_provided() -> None:
    """Given a blacklisted set, BL column appears in the header."""
    rows = [_row("a/x"), _row("b/y")]
    header = format_table(rows, blacklisted=frozenset({"b/y"})).splitlines()[0]
    assert "BL" in header.split()


def test_format_table_bl_marker_only_for_blacklisted_row() -> None:
    """Given two rows where one is blacklisted, only that row's BL column is marked."""
    rows = [_row("a/x"), _row("b/y")]
    table = format_table(rows, blacklisted=frozenset({"b/y"}))
    lines = table.splitlines()
    a_line = next(l for l in lines if "a/x" in l)
    b_line = next(l for l in lines if "b/y" in l)
    a_cells = [c.strip() for c in a_line.split("  ") if c.strip()]
    b_cells = [c.strip() for c in b_line.split("  ") if c.strip()]
    assert b_cells.count("*") == 1
    assert a_cells.count("*") == 0


# --- marker state (fzf TUI helpers) -----------------------------------------

def test_format_marker_state_marks_selected_and_unselected() -> None:
    """Given names and a selected subset, each line carries the right marker."""
    out = format_marker_state(["a/x", "b/y", "c/z"], selected={"b/y"})
    assert out.splitlines() == ["[ ] a/x", "[x] b/y", "[ ] c/z"]


def test_format_marker_state_preserves_input_order() -> None:
    """Given names in a specific order, that order is preserved (fzf is --no-sort)."""
    out = format_marker_state(["z/z", "a/a", "m/m"], selected=frozenset())
    assert [line[4:] for line in out.splitlines()] == ["z/z", "a/a", "m/m"]


def test_format_marker_state_empty_names_returns_empty_string() -> None:
    """Given no names, returns the empty string."""
    assert format_marker_state([], selected={"a/x"}) == ""


def test_parse_marker_state_extracts_only_checked_names() -> None:
    """Given a multi-line state, returns the set of names prefixed with '[x] '."""
    text = "[x] a/x\n[ ] b/y\n[x] c/z\n"
    assert parse_marker_state(text) == frozenset({"a/x", "c/z"})


def test_parse_marker_state_ignores_unchecked_and_blank_lines() -> None:
    """Given '[ ] ' lines and blank lines, only '[x] ' lines contribute."""
    text = "\n[ ] a/x\n\n[x] b/y\n"
    assert parse_marker_state(text) == frozenset({"b/y"})


def test_parse_marker_state_ignores_malformed_lines() -> None:
    """Given lines without a recognized prefix, they are silently dropped."""
    text = "garbage\n[x] a/x\nrandom [x] mid\n[X] b/y\n"
    assert parse_marker_state(text) == frozenset({"a/x"})


def test_format_then_parse_round_trips() -> None:
    """Given a selection, format then parse recovers the same selection."""
    names = ["a/x", "b/y", "c/z", "d/w"]
    selected = frozenset({"a/x", "c/z"})
    text = format_marker_state(names, selected=selected)
    assert parse_marker_state(text) == selected


def test_toggle_marker_line_flips_checked_to_unchecked() -> None:
    """Given a '[x] ' line, toggle returns the '[ ] ' form."""
    assert toggle_marker_line("[x] a/x") == "[ ] a/x"


def test_toggle_marker_line_flips_unchecked_to_checked() -> None:
    """Given a '[ ] ' line, toggle returns the '[x] ' form."""
    assert toggle_marker_line("[ ] a/x") == "[x] a/x"


def test_toggle_marker_line_is_noop_on_unrecognized() -> None:
    """Given a line without a recognized marker, toggle returns it unchanged."""
    assert toggle_marker_line("garbage") == "garbage"
    assert toggle_marker_line("") == ""
    assert toggle_marker_line("[?] foo") == "[?] foo"


def test_toggle_marker_line_preserves_trailing_content() -> None:
    """Given a line with content after the name, that content is preserved."""
    assert toggle_marker_line("[x] a/x  ") == "[ ] a/x  "


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


# --- parse_todo_plan_all (G9) ------------------------------------------------

def test_parse_todo_plan_all_returns_every_unchecked_in_order() -> None:
    """Given mixed checked/unchecked items, returns all unchecked in source order."""
    text = (
        "- [x] one (done)\n"
        "- [ ] alpha\n"
        "- [x] two (done)\n"
        "- [ ] beta\n"
        "- [ ] gamma\n"
    )
    assert parse_todo_plan_all(text) == ["alpha", "beta", "gamma"]


def test_parse_todo_plan_all_skips_struck_through() -> None:
    """Given struck-through unchecked items, they are excluded."""
    text = "- [ ] ~~old~~ replaced\n- [ ] real one\n"
    assert parse_todo_plan_all(text) == ["real one"]


def test_parse_todo_plan_all_no_open_returns_empty() -> None:
    """Given no open tasks, returns an empty list (not None)."""
    assert parse_todo_plan_all("- [x] done\n- [x] also done\n") == []


def test_parse_todo_plan_all_empty_string_returns_empty() -> None:
    """Given empty input, returns an empty list."""
    assert parse_todo_plan_all("") == []


# --- resolve_repo_name (G9) --------------------------------------------------

def test_resolve_repo_name_exact_owner_name_match() -> None:
    """Given an exact 'owner/name' query, returns it when present."""
    known = {"9atatimer/tds-utils", "9atatimer/foo", "other/bar"}
    assert resolve_repo_name("9atatimer/tds-utils", known=known) == ["9atatimer/tds-utils"]


def test_resolve_repo_name_basename_match_unique() -> None:
    """Given a basename query matching exactly one repo, returns that repo."""
    known = {"9atatimer/tds-utils", "9atatimer/foo", "other/bar"}
    assert resolve_repo_name("tds-utils", known=known) == ["9atatimer/tds-utils"]


def test_resolve_repo_name_basename_match_ambiguous() -> None:
    """Given a basename owned by two orgs, returns both matches sorted."""
    known = {"alpha/tds-utils", "beta/tds-utils", "alpha/foo"}
    assert resolve_repo_name("tds-utils", known=known) == [
        "alpha/tds-utils", "beta/tds-utils",
    ]


def test_resolve_repo_name_no_match_returns_empty() -> None:
    """Given a query that matches nothing, returns an empty list."""
    assert resolve_repo_name("nosuch", known={"a/x", "b/y"}) == []


def test_resolve_repo_name_case_insensitive_basename() -> None:
    """Given a query that differs only in case, still matches."""
    known = {"9atatimer/TDS-Utils"}
    assert resolve_repo_name("tds-utils", known=known) == ["9atatimer/TDS-Utils"]


def test_resolve_repo_name_case_insensitive_owner_name() -> None:
    """Given an explicit owner/name with different casing, still matches."""
    known = {"9atatimer/tds-utils"}
    assert resolve_repo_name("9atatimer/TDS-Utils", known=known) == [
        "9atatimer/tds-utils",
    ]


# --- format_zoom (G9) --------------------------------------------------------

def _zoom(
    *,
    name: str = "9atatimer/tds-utils",
    github: GithubInfo | None = None,
    local: LocalInfo | None = None,
    recent_commits: tuple[CommitSummary, ...] = (),
    open_prs: tuple[PRSummary, ...] = (),
    agents: tuple[AgentSession, ...] = (),
    open_tasks: tuple[str, ...] = (),
) -> ZoomData:
    return ZoomData(
        name=name,
        github=github,
        local=local,
        recent_commits=recent_commits,
        open_prs=open_prs,
        agents=agents,
        open_tasks=open_tasks,
    )


def test_format_zoom_includes_repo_name_header() -> None:
    """Given any ZoomData, the first non-blank line names the repo."""
    out = format_zoom(_zoom())
    first = next(line for line in out.splitlines() if line.strip())
    assert "9atatimer/tds-utils" in first


def test_format_zoom_renders_recent_commits() -> None:
    """Given recent commits, each appears with its short sha and subject."""
    out = format_zoom(_zoom(recent_commits=(
        CommitSummary(sha="84578fd", subject="chore(todo-plan): one"),
        CommitSummary(sha="d1d549e", subject="chore(clai): two"),
    )))
    assert "84578fd" in out
    assert "chore(todo-plan): one" in out
    assert "d1d549e" in out


def test_format_zoom_renders_open_prs_with_state() -> None:
    """Given open PRs, each appears with number, title, author, and draft state."""
    out = format_zoom(_zoom(open_prs=(
        PRSummary(number=52, title="feat: thing", author="tstumpf", is_draft=True),
        PRSummary(number=53, title="fix: bug", author="other", is_draft=False),
    )))
    assert "#52" in out
    assert "feat: thing" in out
    assert "draft" in out.lower()
    assert "#53" in out


def test_format_zoom_renders_all_open_tasks_not_just_first() -> None:
    """Given multiple open tasks, every task is listed (not truncated to one)."""
    tasks = tuple(f"task {i}" for i in range(5))
    out = format_zoom(_zoom(open_tasks=tasks))
    for t in tasks:
        assert t in out


def test_format_zoom_renders_local_branch_and_dirty_state() -> None:
    """Given a LocalInfo with dirty=True, the output reflects that."""
    out = format_zoom(_zoom(local=LocalInfo(
        path=Path("/Users/x/workplace/tds-utils"),
        is_dirty=True, ahead=2, behind=0,
        branch="tstumpf/feat/foo",
        last_commit_at=None, next_task=None,
    )))
    assert "tstumpf/feat/foo" in out
    assert "/Users/x/workplace/tds-utils" in out
    assert "dirty" in out.lower()
    assert "2 / 0" in out  # specific ahead/behind line, not any digit


def test_format_zoom_shows_none_markers_for_missing_data() -> None:
    """Given ZoomData with empty sections, those sections render a none/empty marker."""
    out = format_zoom(_zoom())
    # We don't assert a specific marker string -- just that no section blows up
    # and the output is non-empty and includes recognisable section headers.
    lower = out.lower()
    assert "recent commits" in lower or "commits" in lower
    assert "open prs" in lower or "prs" in lower
    assert "tasks" in lower
