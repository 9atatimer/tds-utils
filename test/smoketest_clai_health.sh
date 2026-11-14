#!/usr/bin/env bash
# smoketest_clai_health.sh -- bin/clai-health reports each agent's wiring and
# exits 1 when an installed agent's instructions are not current.
#
# Hermetic: a fake HOME, a fake source tree, a fake repo and a PATH holding
# one stub agent; the real HOME is never read.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$(dirname "${SCRIPT_DIR}")/bin"
WORK=""
TESTS_RUN=0
TESTS_FAILED=0

# --- Action functions ---

cleanup() { [[ -n "${WORK}" && -d "${WORK}" ]] && rm -rf "${WORK}"; return 0; }

fail() {
    echo "FAIL: $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# make_world -- codex installed and on PATH with a config naming its model
# and ast-mcp; claude installed but not on PATH and with no config; the repo
# has two codex skills. Instructions are built by the real agent-instructions.
make_world() {
    WORK=$(mktemp -d)
    mkdir -p "${WORK}/src/clai.d" "${WORK}/home/.codex" "${WORK}/home/.claude" \
        "${WORK}/fakebin" "${WORK}/repo/.codex/skills/a" "${WORK}/repo/.codex/skills/b"
    printf 'CORE RULES\n' >"${WORK}/src/clai.d/AGENT.global.md"
    printf 'model = "gpt-6.1-terra"\n\n[mcp_servers.ast-mcp]\ncommand = "x"\n' \
        >"${WORK}/home/.codex/config.toml"
    printf '#!/bin/sh\nexit 0\n' >"${WORK}/fakebin/codex"
    chmod +x "${WORK}/fakebin/codex"
    printf -- '---\nname: a\n---\n' >"${WORK}/repo/.codex/skills/a/SKILL.md"
    printf -- '---\nname: b\n---\n' >"${WORK}/repo/.codex/skills/b/SKILL.md"
    git -C "${WORK}/repo" init -q
    env_run "${BIN}/agent-instructions" >/dev/null
}

# env_run <cmd...> -- run with the fake HOME, source and PATH.
env_run() {
    HOME="${WORK}/home" XDG_DATA_HOME="" TDS_AGENT_SOURCE="${WORK}/src" \
        PATH="${WORK}/fakebin:/usr/bin:/bin" "$@"
}

row() { grep -E "^\| $2 \|" <<<"$1" || true; }

# --- Flow functions ---

# Given a wired world, When clai-health runs inside the repo with no flags
# (the production invocation), Then codex's row says it is on PATH, its
# instructions are current with their bytes, two repo skills, its config with
# ast-mcp registered, and its model; and the exit status is 0.
test_reports_a_wired_agent() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out rc=0 codex bytes
    out=$(cd "${WORK}/repo" && env_run "${BIN}/clai-health") || rc=$?
    [[ "${rc}" -eq 0 ]] || fail "wired: exit ${rc}, want 0: ${out}"
    codex=$(row "${out}" codex)
    bytes=$(wc -c <"${WORK}/home/.local/share/tds-utils/agents/codex.md" | tr -d ' ')
    grep -qF "| codex | yes | current | ${bytes} | 2 | ~/.codex/config.toml | yes | gpt-6.1-terra |" <<<"${codex}" \
        || fail "codex row: ${codex}"
}

# Given claude installed but absent from PATH and with no config file, When
# clai-health runs, Then its row says so and the home directory never
# appears in the output.
test_reports_what_is_missing_from_tilde() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out claude
    out=$(env_run "${BIN}/clai-health" -r "${WORK}/repo") || true
    claude=$(row "${out}" claude)
    grep -qF '| claude | no | current |' <<<"${claude}" || fail "claude row: ${claude}"
    # A literal ~ label in the output, not a path.
    # shellcheck disable=SC2088
    grep -qF '~/.claude.json (missing)' <<<"${claude}" || fail "claude config: ${claude}"
    if grep -qF "${WORK}/home" <<<"${out}"; then
        fail "home directory in output"
    fi
}

# Given the core changed since the build, When clai-health runs, Then the
# installed agents' rows say stale and the exit status is 1.
test_stale_instructions_exit_one() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out rc=0
    printf 'NEW CORE\n' >"${WORK}/src/clai.d/AGENT.global.md"
    out=$(env_run "${BIN}/clai-health" -r "${WORK}/repo") || rc=$?
    [[ "${rc}" -eq 1 ]] || fail "stale: exit ${rc}, want 1"
    grep -qF '| codex | yes | stale |' <<<"$(row "${out}" codex)" || fail "stale: $(row "${out}" codex)"
    grep -qF '| omp | no | not installed |' <<<"$(row "${out}" omp)" || fail "omp: $(row "${out}" omp)"
}

# --- Main ---

main() {
    trap cleanup EXIT INT TERM HUP
    make_world
    test_reports_a_wired_agent
    test_reports_what_is_missing_from_tilde
    test_stale_instructions_exit_one
    if [[ "${TESTS_FAILED}" -gt 0 ]]; then
        echo "${TESTS_FAILED} failed check(s) in ${TESTS_RUN} tests"
        exit 1
    fi
    echo "PASS: ${TESTS_RUN} tests"
}

main "$@"
