#!/usr/bin/env bash
# Given a shortname not in the package table, When `lmde acquire --latest
# <bogus>` runs, Then it prints nothing, exits 0 (fail-open, never a usage
# error), and notes the unknown shortname on stderr.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc log
    dir="$(scenario_dir latest_unknown)"
    log="${dir}/installlog"
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}"

    rc="$(run_latest "${dir}" totally-not-a-package)"

    assert_eq "${rc}" "0" "--latest on an unknown shortname still exits 0" || return 1
    assert_stdout_empty "${dir}" "unknown shortname prints nothing on stdout" || return 1
    assert_stderr_contains "${dir}" "unknown package shortname" "notes the unknown shortname on stderr" || return 1
}
main "$@"
