#!/usr/bin/env bash
# Given a matching installed stamp and published latest, and no local repo,
# When skills-drift-check runs, Then it is silent and exits 0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc
    dir="$(scenario_dir green)"
    make_lmde_stub "${dir}/bin/lmde" "0.2.31"
    seed_stamp "${dir}/home" "0.2.31"

    rc="$(run_check "${dir}")"

    assert_eq "${rc}" "0" "green when installed == published, no local repo" || return 1
    assert_stdout_empty "${dir}" "green is silent" || return 1
}
main "$@"
