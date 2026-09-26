#!/usr/bin/env bash
# Given no clai on PATH and the credential present ONLY under the retired
# GH_AI_TOOLS_PAT name (GH_PAT_NAATM_PACKAGES_RO empty), When provision.sh
# runs, Then it treats that as no credential: never invokes npm, names
# GH_PAT_NAATM_PACKAGES_RO as what is missing, never provisions, and exits 0
# (fail-open). The retired variable is NOT read (tds-utils#303) -- the token
# behind it is being revoked, so honouring it would keep a dead credential
# load-bearing.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_provision || return 1
    local dir rc
    dir="$(scenario_dir deprecated_pat_var_ignored)"
    write_pins "${dir}" "2.0.0"
    # No clai stub -> clai absent, so the bootstrap path (and write_npmrc) runs.
    make_npm_forbidden_stub "${dir}/bin" "${dir}/npm-called"

    rc="$(TEST_PAT="" TEST_DEPRECATED_PAT="faketoken-retired-name" run_provision "${dir}")"

    # The load-bearing assertion first: whatever the wording, npm must not run.
    assert_file_absent "${dir}/npm-called" \
        "must NOT invoke npm on the retired variable" || return 1
    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_not_provisioned "${dir}" || return 1
    assert_stderr_contains "${dir}" "GH_PAT_NAATM_PACKAGES_RO unset" \
        "a token under the retired name alone is no credential" || return 1
    assert_stderr_not_contains "${dir}" "GH_AI_TOOLS_PAT" \
        "the retired variable is not named, as a source or as a hint" || return 1
}

main "$@"
