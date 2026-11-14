#!/usr/bin/env bash
# smoketest_agent_instructions.sh -- bin/agent-instructions builds each agent's
# instruction file from the core and its fragment, and owns the $HOME link.
#
# Hermetic: a fake HOME and a fake source tree in a temp dir; the real HOME
# is never read or written.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$(dirname "${SCRIPT_DIR}")/bin/agent-instructions"
WORK=""
TESTS_RUN=0
TESTS_FAILED=0

# --- Action functions ---

cleanup() { [[ -n "${WORK}" && -d "${WORK}" ]] && rm -rf "${WORK}"; return 0; }

fail() {
    echo "FAIL: $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# make_world <name> -- a source tree with a core and a codex fragment, and a
# home where claude, codex and opencode are installed (their config dirs
# exist) and omp is not. Prints the world's root.
make_world() {
    local root="${WORK}/$1"
    mkdir -p "${root}/src/clai.d/codex" "${root}/home/.claude" "${root}/home/.codex" \
        "${root}/home/.config/opencode"
    printf 'CORE RULES\n' >"${root}/src/clai.d/AGENT.global.md"
    printf 'CODEX ONLY\n' >"${root}/src/clai.d/codex/AGENT.codex.md"
    printf '%s\n' "${root}"
}

# run_tool <root> [args...] -- the production invocation: the script by
# path, its source and home given the way tds-release gives them.
run_tool() {
    local root=$1
    shift
    HOME="${root}/home" XDG_DATA_HOME="" TDS_AGENT_SOURCE="${root}/src" "${TOOL}" "$@"
}

built() { printf '%s\n' "$1/home/.local/share/tds-utils/agents/$2.md"; }

# --- Flow functions ---

# Given a home with three agents installed, When agent-instructions runs,
# Then each installed agent's link points at its built file, codex's file
# carries the core and its fragment, the others carry only the core, and
# the agent with no config dir gets nothing.
test_builds_and_links_each_installed_agent() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local root out
    root=$(make_world build)
    out=$(run_tool "${root}" 2>&1) || fail "install: non-zero exit: ${out}"
    [[ "$(readlink "${root}/home/.claude/CLAUDE.md")" == "$(built "${root}" claude)" ]] \
        || fail "claude link: $(readlink "${root}/home/.claude/CLAUDE.md" || true)"
    [[ "$(readlink "${root}/home/.codex/AGENTS.md")" == "$(built "${root}" codex)" ]] \
        || fail "codex link"
    [[ "$(readlink "${root}/home/.config/opencode/AGENTS.md")" == "$(built "${root}" opencode)" ]] \
        || fail "opencode link"
    grep -q 'CORE RULES' "$(built "${root}" codex)" || fail "codex file lacks the core"
    grep -q 'CODEX ONLY' "$(built "${root}" codex)" || fail "codex file lacks its fragment"
    grep -q 'CORE RULES' "$(built "${root}" claude)" || fail "claude file lacks the core"
    if grep -q 'CODEX ONLY' "$(built "${root}" claude)"; then
        fail "claude file carries codex's fragment"
    fi
    [[ ! -e "${root}/home/.omp" ]] || fail "omp is not installed but got a directory"
}

# Given an existing link into a checkout (the hand-made kind), When
# agent-instructions runs, Then the link is repointed at the built file.
test_repoints_an_existing_symlink() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local root
    root=$(make_world repoint)
    ln -s "${root}/src/clai.d/AGENT.global.md" "${root}/home/.codex/AGENTS.md"
    run_tool "${root}" >/dev/null 2>&1 || fail "repoint: non-zero exit"
    [[ "$(readlink "${root}/home/.codex/AGENTS.md")" == "$(built "${root}" codex)" ]] \
        || fail "repoint: codex link still $(readlink "${root}/home/.codex/AGENTS.md")"
}

# Given a regular file where an agent's link belongs, When agent-instructions
# runs, Then the file is left as it was and named in the output, and check
# exits 1.
test_never_clobbers_a_regular_file() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local root out rc=0
    root=$(make_world clobber)
    printf 'hand written\n' >"${root}/home/.claude/CLAUDE.md"
    out=$(run_tool "${root}" 2>&1) || true
    [[ "$(cat "${root}/home/.claude/CLAUDE.md")" == "hand written" ]] || fail "regular file was changed"
    grep -q '.claude/CLAUDE.md' <<<"${out}" || fail "regular file not reported: ${out}"
    run_tool "${root}" check >/dev/null 2>&1 || rc=$?
    [[ "${rc}" -eq 1 ]] || fail "check with a regular file: exit ${rc}, want 1"
}

# Given an installed world, When the core changes and check runs, Then check
# exits 1 and changes nothing; after a rebuild it exits 0.
test_check_finds_a_stale_file_and_changes_nothing() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local root rc=0 before
    root=$(make_world stale)
    run_tool "${root}" >/dev/null 2>&1 || fail "stale: install failed"
    run_tool "${root}" check >/dev/null 2>&1 || fail "stale: check after install is not 0"
    printf 'NEW CORE\n' >"${root}/src/clai.d/AGENT.global.md"
    before=$(cat "$(built "${root}" claude)")
    run_tool "${root}" check >/dev/null 2>&1 || rc=$?
    [[ "${rc}" -eq 1 ]] || fail "stale: check exit ${rc}, want 1"
    [[ "$(cat "$(built "${root}" claude)")" == "${before}" ]] || fail "stale: check changed a file"
    run_tool "${root}" >/dev/null 2>&1 || fail "stale: rebuild failed"
    grep -q 'NEW CORE' "$(built "${root}" claude)" || fail "stale: rebuild missed the new core"
}

# Given a fresh world, When agent-instructions runs with -n, Then it names
# what it would do and writes nothing.
test_dry_run_writes_nothing() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local root out
    root=$(make_world dry)
    out=$(run_tool "${root}" -n 2>&1) || fail "dry run: non-zero exit"
    [[ ! -e "${root}/home/.local" && ! -e "${root}/home/.codex/AGENTS.md" ]] \
        || fail "dry run wrote files"
    grep -q 'would' <<<"${out}" || fail "dry run said nothing: ${out}"
}

# Given an installed world whose codex fragment becomes unreadable, When
# agent-instructions runs, Then it exits 1, keeps the previous good file,
# leaves no temp file behind, and check exits 1.
test_a_failed_build_keeps_the_last_good_file() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local root rc=0 before
    root=$(make_world unreadable)
    run_tool "${root}" >/dev/null 2>&1 || fail "unreadable: install failed"
    before=$(cat "$(built "${root}" codex)")
    printf 'CODEX CHANGED\n' >"${root}/src/clai.d/codex/AGENT.codex.md"
    chmod 000 "${root}/src/clai.d/codex/AGENT.codex.md"
    run_tool "${root}" -a codex >/dev/null 2>&1 || rc=$?
    [[ "${rc}" -eq 1 ]] || fail "unreadable: exit ${rc}, want 1"
    [[ "$(cat "$(built "${root}" codex)")" == "${before}" ]] || fail "unreadable: the good file was replaced"
    if ls "$(dirname "$(built "${root}" codex)")" | grep -q '\.md\.'; then
        fail "unreadable: a temp file was left behind"
    fi
    rc=0
    run_tool "${root}" -a codex check >/dev/null 2>&1 || rc=$?
    [[ "${rc}" -eq 1 ]] || fail "unreadable: check exit ${rc}, want 1"
    chmod 644 "${root}/src/clai.d/codex/AGENT.codex.md"
}

# Given -a with an agent it does not know, When it runs, Then it exits 2 and
# names the agents it knows.
test_unknown_agent_is_usage_error() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local root out rc=0
    root=$(make_world usage)
    out=$(run_tool "${root}" -a agy 2>&1) || rc=$?
    [[ "${rc}" -eq 2 ]] || fail "unknown agent: exit ${rc}, want 2"
    grep -q 'claude codex opencode omp' <<<"${out}" || fail "unknown agent: ${out}"
}

# --- Main ---

main() {
    trap cleanup EXIT INT TERM HUP
    WORK=$(mktemp -d)
    test_builds_and_links_each_installed_agent
    test_repoints_an_existing_symlink
    test_never_clobbers_a_regular_file
    test_check_finds_a_stale_file_and_changes_nothing
    test_dry_run_writes_nothing
    test_a_failed_build_keeps_the_last_good_file
    test_unknown_agent_is_usage_error
    if [[ "${TESTS_FAILED}" -gt 0 ]]; then
        echo "${TESTS_FAILED} failed check(s) in ${TESTS_RUN} tests"
        exit 1
    fi
    echo "PASS: ${TESTS_RUN} tests"
}

main "$@"
