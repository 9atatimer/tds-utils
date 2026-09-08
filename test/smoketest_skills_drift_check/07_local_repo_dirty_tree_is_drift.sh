#!/usr/bin/env bash
# Given a local Skills clone whose committed HEAD matches published, but
# with an UNCOMMITTED change under skills/, When skills-drift-check runs,
# Then it reports drift for the dirty tree even though HEAD itself agrees.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc repo
    dir="$(scenario_dir dirty_tree)"
    repo="${dir}/skills-repo"
    make_skills_repo "${repo}" 2
    make_lmde_stub "${dir}/bin/lmde" "0.2.3"
    seed_stamp "${dir}/home" "0.2.3"
    # Uncommitted edit under a version-relevant path.
    printf 'work in progress\n' > "${repo}/skills/scratch.md"

    rc="$(run_check "${dir}" --repo "${repo}")"

    assert_eq "${rc}" "1" "a dirty tree is drift even when HEAD matches published" || return 1
    assert_stdout_contains "${dir}" "uncommitted changes" \
        "names the dirty-tree condition" || return 1
}
main "$@"
