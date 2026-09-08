#!/usr/bin/env bash
# Given `-h`, When skills-drift-check runs, Then it prints usage and exits
# 0 without touching HOME, PATH, or any stub.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    require_check_bin || return 1
    local rc=0 out
    out="$("${CHECK_BIN}" -h 2>&1)" || rc=$?
    assert_eq "${rc}" "0" "-h exits 0" || return 1
    if ! grep -qF "skills-drift-check" <<<"${out}"; then
        echo "FAIL: -h output does not look like usage text"
        echo "--- output ---"; echo "${out}"
        return 1
    fi
}
main "$@"
