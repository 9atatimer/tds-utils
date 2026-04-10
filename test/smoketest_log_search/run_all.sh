#!/bin/zsh
# run_all.sh — orchestrate log_search smoke tests
#
# Runs against real archived logs from the configured log directory.
# Skips gracefully if the archived log directory is missing or contains no .log files.
#
# Usage: ./test/smoketest_log_search/run_all.sh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"

# Create temp index dir before sourcing config.sh (which guards against empty SMOKE_INDEX_DIR).
export SMOKE_INDEX_DIR=$(mktemp -d "${TMPDIR:-/tmp}/log-search-smoke.XXXXXX")

source "${SCRIPT_DIR}/config.sh"

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

red()   { print -n "\033[1;31m$1\033[0m"; }
green() { print -n "\033[1;32m$1\033[0m"; }
bold()  { print -n "\033[1m$1\033[0m"; }

run_test() {
    local script="$1"
    local name="${script:t:r}"
    bold "\n── ${name} ──\n"
    if /bin/zsh "${script}"; then
        green "  ✓ ${name} passed\n"
        (( TESTS_PASSED++ )) || true
    else
        red "  ✗ ${name} failed\n"
        (( TESTS_FAILED++ )) || true
    fi
    (( TESTS_RUN++ )) || true
}

# --- Preflight ---

preflight() {
    if [[ ! -d "${ARCHIVED_DIR}" ]]; then
        bold "SKIP: "
        print "No archived logs at ${ARCHIVED_DIR} — nothing to test."
        exit 0
    fi

    local log_count
    log_count=$(find "${ARCHIVED_DIR}" -name "*.log" -type f 2>/dev/null | wc -l | tr -d ' ')
    if (( log_count == 0 )); then
        bold "SKIP: "
        print "No .log files in ${ARCHIVED_DIR} — nothing to test."
        exit 0
    fi

    if [[ ! -x "${LOG_SEARCH}" ]]; then
        red "FAIL: "
        print "log_search not found at ${LOG_SEARCH}"
        exit 1
    fi
}

# --- Cleanup ---

cleanup() {
    if [[ -n "${SMOKE_INDEX_DIR:-}" && -d "${SMOKE_INDEX_DIR}" ]]; then
        rm -rf "${SMOKE_INDEX_DIR}"
    fi
}
trap cleanup EXIT

# --- Main ---

main() {
    bold "═══ log_search smoke test ═══\n"

    preflight

    for script in "${SCRIPT_DIR}"/[0-9]*.sh; do
        run_test "${script}"
    done

    print ""
    bold "═══ Results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    if (( TESTS_FAILED > 0 )); then
        red ", ${TESTS_FAILED} failed"
    fi
    print " ═══"

    (( TESTS_FAILED == 0 ))
}

main "$@"
