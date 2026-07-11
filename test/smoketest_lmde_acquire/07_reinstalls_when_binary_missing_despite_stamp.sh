#!/usr/bin/env bash
# Given a state stamp recording ast-mcp 0.4.0 but NO prefix binary (the share
# tree was wiped while the stamp survived) and an npm stub whose ast-mcp latest
# is the same 0.4.0, When `lmde acquire` runs, Then it does NOT trust the stamp
# blindly: it REINSTALLS ast-mcp@0.4.0, replants the prefix shim, and relinks
# ~/.local/bin/ast-mcp so the tool is available again.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log
    dir="$(scenario_dir stamp_no_bin)"
    home="${dir}/home"
    log="${dir}/installlog"
    # The stamp says 0.4.0 is installed, but the share tree (prefix bin) is gone.
    mkdir -p "${home}/.local/state/tds-utils/acquire"
    printf '%s\n' "0.4.0" > "${home}/.local/state/tds-utils/acquire/ast-mcp.version"
    make_npm_stub "${dir}/bin" "1.2.3" "0.4.0" "${log}"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ast-mcp@0.4.0" "reinstalls despite a matching stamp when the prefix bin is missing" || return 1
    local astmcp_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/ast-mcp"
    assert_file_present "${astmcp_bin}" "prefix shim replanted" || return 1
    assert_symlink_to "${home}/.local/bin/ast-mcp" "${astmcp_bin}" "ast-mcp relinked on ~/.local/bin" || return 1
}
main "$@"
