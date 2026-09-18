#!/usr/bin/env bash
# Given the credential is present ONLY under the retired GH_AI_TOOLS_PAT name
# (GH_PAT_NAATM_PACKAGES_RO empty, no gh login), When `lmde acquire` runs, Then
# it behaves exactly as "no credential": rc=0 (fail-open), the no-credential
# warning on stderr, and npm install is never attempted. The retired variable
# is NOT read.
#
# The fallback existed to carry unreprovisioned environments across the rename
# and was retired in tds-utils#303 once every surface held the new name. This
# scenario pins the retirement: a token still exported under the old name is
# one the human is about to revoke, so silently continuing to honour it would
# keep a dead credential load-bearing and turn the revocation into an outage
# nobody can explain.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc marker
    dir="$(scenario_dir deprecated_pat_var_ignored)"
    marker="${dir}/install-called"
    make_npm_forbidden_install_stub "${dir}/bin" "1.2.3" "0.4.0" "${marker}"

    rc="$(TEST_PAT="" TEST_DEPRECATED_PAT="faketoken-retired-name" run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_stderr_contains "${dir}" "no credential" \
        "a token under the retired name alone is no credential" || return 1
    assert_stderr_contains "${dir}" "GH_PAT_NAATM_PACKAGES_RO" \
        "stderr names the variable to provision" || return 1
    assert_stderr_not_contains "${dir}" "GH_AI_TOOLS_PAT" \
        "the retired variable is not named, as a source or as a hint" || return 1
    assert_file_absent "${marker}" \
        "npm install must NOT be attempted on the retired variable" || return 1
}
main "$@"
