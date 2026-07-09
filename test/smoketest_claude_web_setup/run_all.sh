#!/usr/bin/env bash
# run_all.sh -- orchestrate the claude-web setup.sh smoke tests
#
# Hermetic and network-free: every scenario stages a copy of setup.sh and runs
# it with a stubbed npm on a fake PATH and a fake $HOME. No real npm, no
# network, no real $HOME. Skips gracefully if python3 is unavailable.
#
# Usage: ./test/smoketest_claude_web_setup/run_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

red()   { printf "\033[1;31m%s\033[0m" "$1"; }
green() { printf "\033[1;32m%s\033[0m" "$1"; }
bold()  { printf "\033[1m%s\033[0m" "$1"; }

run_test() {
    local script="$1" name
    name="$(basename "${script}" .sh)"
    TESTS_RUN=$((TESTS_RUN + 1))
    printf "  %s ... " "$(bold "${name}")"
    if ( bash "${script}" ); then
        printf "%s\n" "$(green PASS)"; TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        printf "%s\n" "$(red FAIL)"; TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

main() {
    # shellcheck source=./config.sh
    source "${SCRIPT_DIR}/config.sh"
    require_setup || return 1
    if ! require_python3; then return 0; fi

    export SMOKE_TMP
    SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/claude-web-setup-smoke.XXXXXX")"
    trap 'rm -rf "${SMOKE_TMP}"' EXIT

    printf "claude-web setup.sh smoke tests (tmp=%s)\n" "${SMOKE_TMP}"
    for script in "${SCRIPT_DIR}"/[0-9][0-9]_*.sh; do
        [[ -f "${script}" ]] || continue
        run_test "${script}"
    done
    printf "\n%d run, %d passed, %d failed\n" "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [[ "${TESTS_FAILED}" -eq 0 ]]
}

main "$@"
