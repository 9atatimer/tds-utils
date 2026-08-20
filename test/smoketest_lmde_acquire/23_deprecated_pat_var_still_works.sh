#!/usr/bin/env bash
# Given the credential is present ONLY under the deprecated GH_AI_TOOLS_PAT
# name, When `lmde acquire` runs, Then it still acquires normally (rc=0, the
# install proceeds) AND stderr warns that the deprecated variable was used and
# names GH_PAT_NAATM_PACKAGES_RO as the replacement.
#
# This is the load-bearing test for the env-var migration. The rename ships
# BEFORE the new name is provisioned anywhere, so the fallback is what keeps
# every unreprovisioned environment -- laptops, cached cloud snapshots, the
# Copilot workspace -- working in the meantime. If this test goes red, the
# migration has become a breaking change and the old environments go dark
# silently, which is the exact failure class the fallback exists to prevent.
#
# The paired assertion matters as much as the pass: acquiring quietly under the
# old name would make "still on the deprecated variable" invisible, and the
# fallback could then never be retired with confidence.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc
    dir="$(scenario_dir deprecated_pat_var)"
    make_npm_stub "${dir}/bin" "1.2.3" "0.4.0" "${dir}/installlog"

    # TEST_PAT_VAR routes the fake token to the OLD name; the harness sets the
    # new one to empty, so this genuinely exercises the fallback branch.
    rc="$(TEST_PAT_VAR=GH_AI_TOOLS_PAT run_acquire "${dir}")"

    assert_eq "${rc}" "0" "acquire still succeeds on the deprecated variable" || return 1
    assert_stderr_contains "${dir}" "DEPRECATED GH_AI_TOOLS_PAT" \
        "stderr flags that the retired variable supplied the credential" || return 1
    assert_stderr_contains "${dir}" "GH_PAT_NAATM_PACKAGES_RO" \
        "stderr names the replacement variable" || return 1
    assert_file_present "${dir}/installlog" \
        "the deprecated name must still reach a real install, not degrade" || return 1
}
main "$@"
