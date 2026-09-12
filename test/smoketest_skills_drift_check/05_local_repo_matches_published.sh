#!/usr/bin/env bash
# Given a local Skills clone whose commit-count version matches the
# published latest (and a matching installed stamp), When
# skills-drift-check runs with SKILLS_REPO_PATH pointed at it, Then all
# three sources agree and it is silent, exit 0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc repo
    dir="$(scenario_dir local_matches)"
    repo="${dir}/skills-repo"
    make_skills_repo "${repo}" 3
    make_lmde_stub "${dir}/bin/lmde" "0.2.4"
    seed_stamp "${dir}/home" "0.2.4"

    rc="$(run_check "${dir}" --repo "${repo}")"

    assert_eq "${rc}" "0" "all three sources agree at 0.2.4" || return 1
    assert_stdout_empty "${dir}" "green is silent even with a local repo in play" || return 1
}
main "$@"
