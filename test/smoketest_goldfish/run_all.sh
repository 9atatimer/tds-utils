#!/usr/bin/env bash
# run_all.sh — orchestrate goldfish smoke tests
#
# Hermetic: every scenario runs against a fresh tmpdir of fake repos. No
# network. No real $HOME walk. Skips gracefully if `git` is unavailable.
#
# Usage: ./test/smoketest_goldfish/run_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v git >/dev/null 2>&1; then
    echo "skip: git not on PATH"
    exit 0
fi

export SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/goldfish-smoke.XXXXXX")"
trap 'rm -rf "${SMOKE_TMP}"' EXIT

source "${SCRIPT_DIR}/config.sh"

# --- Test harness ---

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

main() {
    printf "goldfish smoke tests (tmp=%s)\n" "${SMOKE_TMP}"
    for script in "${SCRIPT_DIR}"/[0-9][0-9]_*.sh; do
        [[ -f "${script}" ]] || continue
        run_test "${script}"
    done
    printf "\n%d run, %d passed, %d failed\n" \
        "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [[ "${TESTS_FAILED}" -eq 0 ]]
}

main "$@"
