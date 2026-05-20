#!/usr/bin/env bash
# 09_help_flag.sh
# Given no agent, when clai is invoked with --help or -h, then it prints usage
# (covering --list-agents) and exits 0 without launching anything.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    init_scenario "09_help_flag"

    local flag out rc
    for flag in --help -h; do
        rc=0
        out="$(run_clai workdir "${flag}")" || rc=$?
        if (( rc != 0 )); then
            echo "FAIL: clai ${flag} exited ${rc}" >&2; return 1
        fi
        if ! grep -q 'Usage:' <<<"${out}"; then
            echo "FAIL: clai ${flag} output missing Usage:" >&2
            echo "${out}" >&2; return 1
        fi
        if ! grep -q -- '--list-agents' <<<"${out}"; then
            echo "FAIL: clai ${flag} output does not mention --list-agents:" >&2
            echo "${out}" >&2; return 1
        fi
    done
}

main "$@"
