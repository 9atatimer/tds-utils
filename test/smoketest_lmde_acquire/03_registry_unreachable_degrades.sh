#!/usr/bin/env bash
# Given a pre-seeded installed ast-mcp 0.3.0 (stamp + symlink) and an npm stub
# where both view and install fail, When `lmde acquire` runs, Then rc=0, the
# existing ~/.local/bin/ast-mcp symlink is left intact (not removed), and stderr
# warns the registry is unreachable while naming the kept-but-possibly-stale
# 0.3.0 -- and, for clai (not pre-seeded), warns it is unavailable this run.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home seeded_target
    dir="$(scenario_dir registry_down)"
    home="${dir}/home"
    seeded_target="$(seed_installed "${home}" "ast-mcp" "ast-mcp" "0.3.0")"
    make_npm_fail_stub "${dir}/bin"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    # The pre-existing symlink must survive an unreachable-registry run.
    assert_symlink_to "${home}/.local/bin/ast-mcp" "${seeded_target}" "kept ast-mcp symlink intact" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/ast-mcp.version")" "0.3.0" "ast-mcp stamp unchanged" || return 1
    assert_stderr_contains "${dir}" "0.3.0" "stderr names the kept-but-stale ast-mcp version" || return 1
    assert_stderr_contains "${dir}" "ast-mcp" "stderr mentions ast-mcp degrade" || return 1
    assert_stderr_contains "${dir}" "clai" "stderr warns clai unavailable this run" || return 1
    # clai was never installed, so no symlink should have appeared.
    assert_file_absent "${home}/.local/bin/clai" "clai must not be linked when it could not be resolved" || return 1
}
main "$@"
