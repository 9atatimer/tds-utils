#!/usr/bin/env bash
# Given an installed stamp older than the published latest, When
# skills-drift-check runs, Then it reports drift naming both versions and
# exits 1.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc
    dir="$(scenario_dir installed_behind)"
    make_lmde_stub "${dir}/bin/lmde" "0.2.31"
    seed_stamp "${dir}/home" "0.2.8"

    rc="$(run_check "${dir}")"

    assert_eq "${rc}" "1" "drift when installed lags published" || return 1
    assert_stdout_contains "${dir}" "DRIFT: installed 0.2.8 != published 0.2.31" \
        "names both the installed and published versions" || return 1
}
main "$@"
