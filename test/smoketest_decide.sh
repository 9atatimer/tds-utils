#!/usr/bin/env bash
# smoketest_decide.sh -- run the decide node suites (lib/decide, bin/decide),
# then drive the real bin/decide: --help exits 0, and `run` with no
# backend environment exits 2 (config) before reading anything or touching
# the network.
#
# Requires node >= 20 on PATH. Exit 0 = pass. No network, no side effects.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Action functions ---

run_suites() {
    node --test \
        "${REPO_ROOT}/test/decide_schema.test.mjs" \
        "${REPO_ROOT}/test/decide_backend.test.mjs" \
        "${REPO_ROOT}/test/decide_answers.test.mjs" \
        "${REPO_ROOT}/test/decide_failure.test.mjs" \
        "${REPO_ROOT}/test/decide_io.test.mjs"
}

expect_equal() {
    local label="$1" want="$2" got="$3"
    if [[ "${got}" != "${want}" ]]; then
        echo "FAIL: ${label}: want '${want}', got '${got}'" >&2
        return 1
    fi
}

check_help() {
    local out code=0
    out=$(node "${REPO_ROOT}/bin/decide" --help) || code=$?
    expect_equal "decide --help exit" 0 "${code}"
    grep -q '^usage: decide run' <<< "${out}"
    echo "PASS: bin/decide --help"
}

# `run` with every DECIDE_* variable unset: a config failure (exit 2) with a
# JSON failure line on stdout, decided before stdin is read.
check_run_without_env() {
    local out code=0 node_bin
    node_bin="$(command -v node)"
    out=$(env -i PATH="$(dirname "${node_bin}")" HOME="${HOME}" \
        "${node_bin}" "${REPO_ROOT}/bin/decide" run < /dev/null 2> /dev/null) || code=$?
    expect_equal "decide run without env exit" 2 "${code}"
    grep -q '"class":"config"' <<< "${out}"
    echo "PASS: bin/decide run without env exits 2"
}

# --- Flow functions ---

run_all() {
    run_suites
    check_help
    check_run_without_env
}

# --- Main ---

main() {
    run_all
}

main "$@"
