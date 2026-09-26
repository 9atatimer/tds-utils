#!/usr/bin/env bash
# Given the credential is present ONLY under the retired GH_AI_TOOLS_PAT name
# (GH_PAT_NAATM_PACKAGES_RO empty, no gh login), When `lmde acquire` runs, Then
# it behaves exactly as "no credential": rc=0 (fail-open), the no-credential
# warning on stderr, and npm install is never attempted. The retired variable
# is NOT read.
#
# The fallback existed to carry unreprovisioned environments across the rename
# and was retired in tds-utils#303. This scenario pins the retirement: a token still exported under the old name is
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

    # The load-bearing assertion first: whatever the wording, npm must not run.
    assert_file_absent "${marker}" \
        "npm install must NOT be attempted on the retired variable" || return 1
    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_stderr_contains "${dir}" "no credential" \
        "a token under the retired name alone is no credential" || return 1
    assert_stderr_contains "${dir}" "GH_PAT_NAATM_PACKAGES_RO" \
        "stderr names the variable to provision" || return 1
    assert_stderr_not_contains "${dir}" "GH_AI_TOOLS_PAT" \
        "the retired variable is not named, as a source or as a hint" || return 1

    # --check shares acquire_token; pin that verb too, so the retirement is
    # not held up by one call site.
    local cdir crc
    cdir="$(scenario_dir deprecated_pat_var_ignored_check)"
    crc="$(TEST_PAT="" TEST_DEPRECATED_PAT="faketoken-retired-name" run_check "${cdir}")"
    assert_eq "${crc}" "0" "advisory check exits 0" || return 1
    assert_stdout_empty "${cdir}" "no advisory on the retired variable alone" || return 1
    assert_stderr_contains "${cdir}" "advisory update check skipped" \
        "--check treats the retired variable as no credential" || return 1
}
main "$@"
