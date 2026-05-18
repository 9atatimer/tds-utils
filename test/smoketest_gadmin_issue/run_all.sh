#!/usr/bin/env bash
# run_all.sh — orchestrate gadmin-issue smoke tests
#
# Hermetic: scenarios test the pure-logic pieces of the Issues subsystem.
# No network. Anything that needs a live GitHub / NATS / aggregator is
# marked SKIP via the corresponding require_* check.
#
# Usage: ./test/smoketest_gadmin_issue/run_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Test harness (definitions; control flow lives in main) ------------------

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

red()   { printf "\033[1;31m%s\033[0m" "$1"; }
green() { printf "\033[1;32m%s\033[0m" "$1"; }
yellow(){ printf "\033[1;33m%s\033[0m" "$1"; }
bold()  { printf "\033[1m%s\033[0m" "$1"; }

run_test() {
    local script="$1"
    local name
    name="$(basename "${script}" .sh)"
    TESTS_RUN=$((TESTS_RUN + 1))
    printf "  %s ... " "$(bold "${name}")"
    local out rc
    out="$(bash "${script}" 2>&1)" && rc=0 || rc=$?
    if [[ "${rc}" -eq 0 ]]; then
        printf "%s\n" "$(green PASS)"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    elif [[ "${rc}" -eq 77 ]]; then
        printf "%s\n" "$(yellow SKIP)"
    else
        printf "%s\n" "$(red FAIL)"
        printf "%s\n" "${out}" | sed 's/^/      /'
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

# --- Main --------------------------------------------------------------------

main() {
    if ! command -v node >/dev/null 2>&1; then
        echo "skip: node not on PATH"
        return 0
    fi

    export SMOKE_TMP
    SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/gadmin-issue-smoke.XXXXXX")"
    trap 'rm -rf "${SMOKE_TMP}"' EXIT

    # shellcheck source=./config.sh
    source "${SCRIPT_DIR}/config.sh"

    echo "running gadmin-issue smoke tests"
    echo "  repo: $(cd "${SCRIPT_DIR}/../.." && pwd)"
    echo "  tmp:  ${SMOKE_TMP}"
    echo ""

    for scenario in "${SCRIPT_DIR}"/[0-9][0-9]_*.sh; do
        [[ -e "${scenario}" ]] || continue
        run_test "${scenario}"
    done

    echo ""
    echo "$(bold Results:) ran=${TESTS_RUN} passed=${TESTS_PASSED} failed=${TESTS_FAILED}"
    if [[ "${TESTS_FAILED}" -gt 0 ]]; then
        return 1
    fi
}

main "$@"
