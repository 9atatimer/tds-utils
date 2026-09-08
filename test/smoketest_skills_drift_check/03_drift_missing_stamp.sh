#!/usr/bin/env bash
# Given NO installed stamp at all (skills never acquired on this machine)
# but the registry resolves fine, When skills-drift-check runs, Then it
# reports drift -- NOT silent green -- naming the missing stamp.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc
    dir="$(scenario_dir missing_stamp)"
    make_lmde_stub "${dir}/bin/lmde" "0.2.31"
    # Deliberately no seed_stamp call -- no stamp file exists.

    rc="$(run_check "${dir}")"

    assert_eq "${rc}" "1" "a missing stamp is drift, not silent green" || return 1
    assert_stdout_contains "${dir}" "never acquired on this machine" \
        "names the missing-stamp condition, not a bare version mismatch" || return 1
}
main "$@"
