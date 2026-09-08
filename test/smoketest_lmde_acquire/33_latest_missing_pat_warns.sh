#!/usr/bin/env bash
# Given no credential (TEST_PAT empty, no gh on PATH), When
# `lmde acquire --latest skills` runs, Then it prints nothing, exits 0
# (fail-open), and warns on stderr instead of crashing.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc log
    dir="$(scenario_dir latest_no_pat)"
    log="${dir}/installlog"
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" "9.9.9"

    rc="$(TEST_PAT="" run_latest "${dir}" skills)"

    assert_eq "${rc}" "0" "--latest with no credential still exits 0" || return 1
    assert_stdout_empty "${dir}" "no credential prints nothing on stdout" || return 1
    assert_stderr_contains "${dir}" "no credential" "warns about the missing credential on stderr" || return 1
}
main "$@"
