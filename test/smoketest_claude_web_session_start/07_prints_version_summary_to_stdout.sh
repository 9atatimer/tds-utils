#!/usr/bin/env bash
# Given acquire state stamps in the fake HOME, When session-start.sh runs,
# Then it prints a short provisioning summary to STDOUT naming the stamped
# versions -- a SessionStart hook's stdout is added to the session context,
# which is how drift becomes visible in-session (template-tools#381,
# SANDBOX-LIFECYCLE.DESIGN.md Goal 5).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_session || return 1
    local dir rc
    dir="$(scenario_dir summary)"
    make_clai_stub "${dir}/bin"
    make_lmde_stub "${dir}/bin"
    mkdir -p "${dir}/home/.local/state/tds-utils/acquire"
    printf '1.2.3\n' > "${dir}/home/.local/state/tds-utils/acquire/clai.version"
    printf '0.4.0\n' > "${dir}/home/.local/state/tds-utils/acquire/ast-mcp.version"

    rc="$(run_session "${dir}")"

    assert_eq "${rc}" "0" "exit 0" || return 1
    assert_stdout_contains "${dir}" "clai 1.2.3" "summary names the stamped clai version" || return 1
    assert_stdout_contains "${dir}" "ast-mcp 0.4.0" "summary names the stamped ast-mcp version" || return 1
}
main "$@"
