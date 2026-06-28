#!/usr/bin/env bash
# run_all.sh — orchestrate the clai ast-mcp enable-hook smoke tests
#
# Hermetic and network-free: every scenario runs a clai pre-hook against a fresh
# throwaway $HOME of fixture agent configs. No real user config is touched, no
# install is performed. Skips gracefully if `jq` is unavailable.
#
# Usage: ./test/smoketest_clai_ast_mcp/run_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Test harness (definitions; control flow lives in main) ------------------

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

red()   { printf "\033[1;31m%s\033[0m" "$1"; }
green() { printf "\033[1;32m%s\033[0m" "$1"; }
bold()  { printf "\033[1m%s\033[0m" "$1"; }

run_test() {
    local script="$1"
    local name
    name="$(basename "${script}" .sh)"
    TESTS_RUN=$((TESTS_RUN + 1))
    printf "  %s ... " "$(bold "${name}")"
    if ( bash "${script}" ); then
        printf "%s\n" "$(green PASS)"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        printf "%s\n" "$(red FAIL)"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

# --- Main --------------------------------------------------------------------

main() {
    # shellcheck source=./config.sh
    source "${SCRIPT_DIR}/config.sh"

    if ! require_jq; then
        return 0
    fi

    export SMOKE_TMP
    SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/clai-ast-mcp-smoke.XXXXXX")"
    trap 'rm -rf "${SMOKE_TMP}"' EXIT

    printf "clai ast-mcp enable-hook smoke tests (tmp=%s)\n" "${SMOKE_TMP}"
    for script in "${SCRIPT_DIR}"/[0-9][0-9]_*.sh; do
        [[ -f "${script}" ]] || continue
        run_test "${script}"
    done
    printf "\n%d run, %d passed, %d failed\n" \
        "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [[ "${TESTS_FAILED}" -eq 0 ]]
}

main "$@"
