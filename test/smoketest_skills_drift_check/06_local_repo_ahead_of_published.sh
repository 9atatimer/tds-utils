#!/usr/bin/env bash
# Given a local Skills clone with unpublished commits (its computed version
# is ahead of the registry latest), When skills-drift-check runs, Then it
# reports drift naming the local repo path, exit 1.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc repo
    dir="$(scenario_dir local_ahead)"
    repo="${dir}/skills-repo"
    make_skills_repo "${repo}" 5
    make_lmde_stub "${dir}/bin/lmde" "0.2.3"
    seed_stamp "${dir}/home" "0.2.3"

    rc="$(run_check "${dir}" --repo "${repo}")"

    assert_eq "${rc}" "1" "local ahead of published is drift" || return 1
    assert_stdout_contains "${dir}" "local repo HEAD (0.2.6) != published 0.2.3" \
        "names the local-vs-published mismatch" || return 1
    assert_stdout_contains "${dir}" "${repo}" \
        "names the repo path so it's actionable" || return 1
}
main "$@"
