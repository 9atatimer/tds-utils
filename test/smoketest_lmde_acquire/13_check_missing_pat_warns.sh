#!/usr/bin/env bash
# Given no GH_AI_TOOLS_PAT in the environment, When `lmde acquire --check` runs,
# Then it cannot query GitHub Packages: it prints nothing on stdout, warns on
# stderr that the token is unset and the check was skipped, and exits 0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc
    dir="$(scenario_dir check_no_pat)"
    # A stub is present but should never be consulted: the token guard trips first.
    make_npm_stub "${dir}/bin" "2.0.0" "0.5.0" "${dir}/installlog"

    rc="$(TEST_PAT="" run_check "${dir}")"

    assert_eq "${rc}" "0" "advisory check always exits 0 without a token" || return 1
    assert_stdout_empty "${dir}" "no advisory without a token to query the registry" || return 1
    assert_stderr_contains "${dir}" "GH_AI_TOOLS_PAT unset" "stderr names the missing token" || return 1
}
main "$@"
