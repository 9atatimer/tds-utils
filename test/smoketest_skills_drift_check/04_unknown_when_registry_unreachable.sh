#!/usr/bin/env bash
# Given the lmde stub cannot resolve a latest version (registry unreachable
# / no credential, mirroring latest_run's own fail-open contract), When
# skills-drift-check runs, Then it exits 2, prints nothing on stdout (no
# false drift), and notes why on stderr.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc
    dir="$(scenario_dir unreachable)"
    make_lmde_stub "${dir}/bin/lmde" ""
    seed_stamp "${dir}/home" "0.2.8"

    rc="$(run_check "${dir}")"

    assert_eq "${rc}" "2" "unresolvable registry is UNKNOWN, not drift" || return 1
    assert_stdout_empty "${dir}" "unknown state prints no DRIFT lines" || return 1
    assert_stderr_contains "${dir}" "could not resolve" \
        "explains why on stderr" || return 1
}
main "$@"
