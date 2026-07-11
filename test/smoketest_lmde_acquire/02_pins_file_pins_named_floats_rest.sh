#!/usr/bin/env bash
# Given a --pins file that sets only CLAI_VERSION="1.0.0" (no AST_MCP_VERSION)
# and an npm stub whose clai "latest" is a DIFFERENT 9.9.9 while ast-mcp
# latest=0.4.0, When `lmde acquire --pins <file>` runs, Then clai installs at
# exactly the pinned 1.0.0 (NOT the 9.9.9 latest -- the pin is honored, view is
# not needed), ast-mcp floats to 0.4.0, rc=0, and both stamps/symlinks reflect
# 1.0.0 and 0.4.0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log pins
    dir="$(scenario_dir pins_named)"
    home="${dir}/home"
    log="${dir}/installlog"
    pins="${dir}/pins.env"
    cat > "${pins}" <<'EOF'
# a --pins override that pins clai and floats ast-mcp
CLAI_VERSION="1.0.0"
EOF
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${log}"

    rc="$(run_acquire "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@1.0.0" "clai installed at the pinned version" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/clai@9.9.9" "clai must NOT float to latest when pinned" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ast-mcp@0.4.0" "ast-mcp floats to latest" || return 1

    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/clai.version")" "1.0.0" "clai stamp pinned" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/ast-mcp.version")" "0.4.0" "ast-mcp stamp floated" || return 1

    local clai_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/clai"
    assert_symlink_to "${home}/.local/bin/clai" "${clai_bin}" "clai symlink present" || return 1
}
main "$@"
