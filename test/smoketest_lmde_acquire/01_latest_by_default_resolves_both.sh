#!/usr/bin/env bash
# Given no --pins and an npm stub reporting clai latest=1.2.3 and ast-mcp
# latest=0.4.0, When `lmde acquire` runs, Then rc=0, both packages install at
# their latest, ~/.local/bin/{clai,ast-mcp} symlink to the installed shims, the
# state stamps record 1.2.3 and 0.4.0, and stderr names both installs.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log
    dir="$(scenario_dir latest_both)"
    home="${dir}/home"
    log="${dir}/installlog"
    make_npm_stub "${dir}/bin" "1.2.3" "0.4.0" "${log}"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@1.2.3" "clai installed at latest" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ast-mcp@0.4.0" "ast-mcp installed at latest" || return 1

    local clai_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/clai"
    local astmcp_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/ast-mcp"
    assert_symlink_to "${home}/.local/bin/clai" "${clai_bin}" "clai on ~/.local/bin" || return 1
    assert_symlink_to "${home}/.local/bin/ast-mcp" "${astmcp_bin}" "ast-mcp on ~/.local/bin" || return 1

    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/clai.version")" "1.2.3" "clai stamp" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/ast-mcp.version")" "0.4.0" "ast-mcp stamp" || return 1

    assert_stderr_contains "${dir}" "clai 1.2.3" "stderr names installed clai version" || return 1
    assert_stderr_contains "${dir}" "ast-mcp 0.4.0" "stderr names installed ast-mcp version" || return 1
}
main "$@"
