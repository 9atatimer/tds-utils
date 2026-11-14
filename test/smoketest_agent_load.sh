#!/usr/bin/env bash
# smoketest_agent_load.sh -- bin/agent-load reports what each agent loads at
# session start, and exits 1 when an agent is over the byte budget.
#
# Hermetic: a fake HOME and a fake repo in a temp dir; no network, and the
# real HOME is never read.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$(dirname "${SCRIPT_DIR}")/bin/agent-load"
WORK=""
FAKE_HOME=""
REPO=""
TESTS_RUN=0
TESTS_FAILED=0

# --- Action functions ---

cleanup() { [[ -n "${WORK}" && -d "${WORK}" ]] && rm -rf "${WORK}"; return 0; }

fail() {
    echo "FAIL: $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# bytes_file <path> <n> -- write a file of exactly n bytes.
bytes_file() {
    mkdir -p "$(dirname "$1")"
    head -c "$2" /dev/zero | tr '\0' 'x' >"$1"
}

# skill <dir> <name> <description> -- a SKILL.md with one-line frontmatter.
skill() {
    mkdir -p "$1/$2"
    printf -- '---\nname: %s\ndescription: %s\n---\n\n# body\n' "$2" "$3" >"$1/$2/SKILL.md"
}

# make_world -- global files of 1000 (claude) and 400 (codex) bytes, a repo
# whose AGENT.md is 300 bytes behind CLAUDE.md and AGENTS.md symlinks, and two
# skills. opencode and omp have no global file.
make_world() {
    WORK=$(mktemp -d)
    FAKE_HOME="${WORK}/home"
    REPO="${WORK}/repo"
    mkdir -p "${FAKE_HOME}" "${REPO}"
    bytes_file "${WORK}/global.claude.md" 1000
    bytes_file "${WORK}/global.codex.md" 400
    mkdir -p "${FAKE_HOME}/.claude" "${FAKE_HOME}/.codex"
    ln -s "${WORK}/global.claude.md" "${FAKE_HOME}/.claude/CLAUDE.md"
    ln -s "${WORK}/global.codex.md" "${FAKE_HOME}/.codex/AGENTS.md"
    bytes_file "${REPO}/AGENT.md" 300
    ln -s AGENT.md "${REPO}/CLAUDE.md"
    ln -s AGENT.md "${REPO}/AGENTS.md"
    git -C "${REPO}" init -q
    skill "${REPO}/.claude/skills" alpha "ten bytes."
    skill "${REPO}/.claude/skills" beta "five."
    skill "${REPO}/.codex/skills" alpha "ten bytes."
}

# row <output> <agent> -- the table row for one agent.
row() { grep -E "^\| $2 \|" <<<"$1" || true; }

# --- Flow functions ---

# Given a repo and agents under budget, When agent-load runs from inside the
# repo with no flags (the production invocation), Then each agent's row shows
# its global and repo bytes and total, and the exit status is 0.
test_reports_each_agent_and_passes_under_budget() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out rc=0
    out=$(cd "${REPO}" && HOME="${FAKE_HOME}" "${TOOL}") || rc=$?
    [[ "${rc}" -eq 0 ]] || fail "under budget: exit ${rc}, want 0: ${out}"
    grep -qF '| claude | ~/.claude/CLAUDE.md | 1000 | CLAUDE.md | 300 | 1300 | 2 | 15 | ok |' <<<"$(row "${out}" claude)" \
        || fail "claude row: $(row "${out}" claude)"
    grep -qF '| codex | ~/.codex/AGENTS.md | 400 | AGENTS.md | 300 | 700 | 1 | 10 | ok |' <<<"$(row "${out}" codex)" \
        || fail "codex row: $(row "${out}" codex)"
}

# Given an agent with no global file, When agent-load runs, Then its row
# says the file is missing and counts it as 0 bytes.
test_missing_global_file_counts_zero() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out
    out=$(HOME="${FAKE_HOME}" "${TOOL}" -r "${REPO}") || true
    grep -qF '| omp | ~/.omp/agent/AGENTS.md (missing) | 0 | AGENTS.md | 300 | 300 |' <<<"$(row "${out}" omp)" \
        || fail "omp row: $(row "${out}" omp)"
}

# Given a budget smaller than claude's total, When agent-load runs, Then
# claude's row says over, codex's says ok, and the exit status is 1.
test_over_budget_exits_one() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out rc=0
    out=$(HOME="${FAKE_HOME}" "${TOOL}" -r "${REPO}" -b 1000) || rc=$?
    [[ "${rc}" -eq 1 ]] || fail "over budget: exit ${rc}, want 1"
    grep -qE '\| over \|$' <<<"$(row "${out}" claude)" || fail "claude not over: $(row "${out}" claude)"
    grep -qE '\| ok \|$' <<<"$(row "${out}" codex)" || fail "codex not ok: $(row "${out}" codex)"
}

# Given -a codex, When agent-load runs, Then only codex's row is printed.
test_one_agent_only() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out
    out=$(HOME="${FAKE_HOME}" "${TOOL}" -r "${REPO}" -a codex) || true
    [[ -n "$(row "${out}" codex)" ]] || fail "-a codex: no codex row: ${out}"
    [[ -z "$(row "${out}" claude)" ]] || fail "-a codex: claude row printed"
}

# Given an agent name agent-load does not know, When it runs, Then it exits 2
# and names the agents it knows.
test_unknown_agent_is_usage_error() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out rc=0
    out=$(HOME="${FAKE_HOME}" "${TOOL}" -r "${REPO}" -a agy 2>&1) || rc=$?
    [[ "${rc}" -eq 2 ]] || fail "unknown agent: exit ${rc}, want 2"
    grep -q 'claude codex opencode omp' <<<"${out}" || fail "unknown agent: no agent list: ${out}"
}

# --- Main ---

main() {
    trap cleanup EXIT INT TERM HUP
    make_world
    test_reports_each_agent_and_passes_under_budget
    test_missing_global_file_counts_zero
    test_over_budget_exits_one
    test_one_agent_only
    test_unknown_agent_is_usage_error
    if [[ "${TESTS_FAILED}" -gt 0 ]]; then
        echo "${TESTS_FAILED} failed check(s) in ${TESTS_RUN} tests"
        exit 1
    fi
    echo "PASS: ${TESTS_RUN} tests"
}

main "$@"
