#!/usr/bin/env bash
# Given GH_AI_TOOLS_PAT is unset, When `lmde acquire` runs, Then rc=0, stderr
# carries a clear GH_AI_TOOLS_PAT / read:packages warning, and no npm install is
# attempted (degrades to whatever is already installed). A forbidden-install
# stub proves install is never reached.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc marker
    dir="$(scenario_dir no_pat)"
    marker="${dir}/install-called"
    make_npm_forbidden_install_stub "${dir}/bin" "1.2.3" "0.4.0" "${marker}"

    rc="$(TEST_PAT="" run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_stderr_contains "${dir}" "GH_AI_TOOLS_PAT" "stderr names the missing token env var" || return 1
    assert_stderr_contains "${dir}" "read:packages" "stderr explains the classic read:packages requirement" || return 1
    assert_file_absent "${marker}" "npm install must NOT be attempted without a token" || return 1
}
main "$@"
