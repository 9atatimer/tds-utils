#!/usr/bin/env bash
# smoketest_agent_budget.sh -- the instructions every agent loads in this repo
# stay within agent-load's budget (32 KiB: Codex's project-doc limit and the
# agent-instructions skill's target).
#
# Builds each agent's global file from this checkout's clai.d/ with
# bin/agent-instructions into a scratch HOME, then runs bin/agent-load on this
# repo. A change that grows clai.d/AGENT.global.md, an agent's fragment or
# AGENT.md past the budget fails here (.github/scripts/changed-scopes.sh maps
# those files to smoketests). Hermetic: scratch HOME, no network.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
WORK=""
TESTS_RUN=0
TESTS_FAILED=0

# --- Action functions ---

cleanup() { [[ -n "${WORK}" && -d "${WORK}" ]] && rm -rf "${WORK}"; return 0; }

fail() {
    echo "FAIL: $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# make_home -- a scratch HOME where every agent counts as installed.
make_home() {
    local home="${WORK}/home"
    mkdir -p "${home}/.claude" "${home}/.codex" "${home}/.config/opencode" "${home}/.omp/agent"
    printf '%s\n' "${home}"
}

# --- Flow functions ---

# Given this checkout's instruction sources, When every agent's file is built
# and measured against this repo, Then every agent is within budget.
test_every_agent_is_within_budget() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home out rc=0
    home=$(make_home)
    env -u TDS_AGENT_SOURCE -u XDG_DATA_HOME HOME="${home}" \
        "${REPO_DIR}/bin/agent-instructions" >/dev/null || fail "agent-instructions failed"
    out=$(env -u XDG_DATA_HOME HOME="${home}" "${REPO_DIR}/bin/agent-load" -r "${REPO_DIR}") || rc=$?
    printf '%s\n' "${out}"
    [[ "${rc}" -eq 0 ]] || fail "an agent is over budget (agent-load exit ${rc})"
}

# Given a repo file that alone exceeds the budget, When agent-load measures
# it, Then it exits 1 (the check can fail).
test_over_budget_fails() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home repo rc=0
    home=$(make_home)
    repo="${WORK}/big"
    mkdir -p "${repo}"
    head -c 40000 /dev/zero | tr '\0' 'x' >"${repo}/AGENT.md"
    ln -s AGENT.md "${repo}/CLAUDE.md"
    ln -s AGENT.md "${repo}/AGENTS.md"
    env -u XDG_DATA_HOME HOME="${home}" "${REPO_DIR}/bin/agent-load" -r "${repo}" >/dev/null || rc=$?
    [[ "${rc}" -eq 1 ]] || fail "over budget: exit ${rc}, want 1"
}

# --- Main ---

main() {
    trap cleanup EXIT INT TERM HUP
    WORK=$(mktemp -d)
    test_every_agent_is_within_budget
    test_over_budget_fails
    if [[ "${TESTS_FAILED}" -gt 0 ]]; then
        echo "${TESTS_FAILED} failed check(s) in ${TESTS_RUN} tests"
        exit 1
    fi
    echo "PASS: ${TESTS_RUN} tests"
}

main "$@"
