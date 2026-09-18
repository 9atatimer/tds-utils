#!/usr/bin/env bash
# run_all.sh -- orchestrate the `skills-drift-check` smoke tests
#
# Hermetic and network-free: every scenario runs the real
# bin/skills-drift-check with a fake HOME, a stubbed `lmde` on a fake PATH,
# and (where relevant) a real, throwaway local git repo. No real HOME, no
# real registry, no network.
#
# Usage: ./test/smoketest_skills_drift_check/run_all.sh

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
        printf "%s\n" "$(green PASS)"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        printf "%s\n" "$(red FAIL)"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

main() {
    # shellcheck source=./config.sh
    source "${SCRIPT_DIR}/config.sh"
    require_check_bin || return 1

    export SMOKE_TMP
    SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")"
    trap 'rm -rf "${SMOKE_TMP}"' EXIT

    printf "skills-drift-check smoke tests (tmp=%s)\n" "${SMOKE_TMP}"
    for script in "${SCRIPT_DIR}"/[0-9][0-9]_*.sh; do
        [[ -f "${script}" ]] || continue
        run_test "${script}"
    done
    printf "\n%d run, %d passed, %d failed\n" \
        "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [[ "${TESTS_FAILED}" -eq 0 ]]
}

main "$@"
