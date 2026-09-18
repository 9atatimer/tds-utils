#!/usr/bin/env bash
# Given SKILLS_REPO_PATH points at a directory that doesn't exist (no local
# clone there), When skills-drift-check runs, Then the local source is
# skipped -- not reported as drift -- and the result is green as long as
# installed/published agree.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc
    dir="$(scenario_dir absent_local)"
    make_lmde_stub "${dir}/bin/lmde" "0.2.31"
    seed_stamp "${dir}/home" "0.2.31"

    rc="$(run_check "${dir}" --repo "${dir}/no-such-repo")"

    assert_eq "${rc}" "0" "an absent local clone is skipped, not drift" || return 1
    assert_stdout_empty "${dir}" "still silent/green" || return 1
}
main "$@"
