#!/usr/bin/env bash
# Given a reachable repo checkout carrying a committed .mcp.json, When setup.sh
# runs, Then in addition to user scope it PRE-INSTALLS the project-local
# .ast-mcp the committed entry points at, so that entry resolves at first
# connect instead of shadowing the user-scope server with a missing binary
# (the "both scopes" safety, #99).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    require_python3 || return 0
    local dir rc proj
    dir="$(scenario_dir project)"
    make_npm_stub "${dir}/bin"
    # A fixture "checkout" with a committed .mcp.json.
    proj="${dir}/checkout"
    mkdir -p "${proj}"
    printf '{ "mcpServers": { "ast-mcp": { "command": "${CLAUDE_PROJECT_DIR:-.}/.ast-mcp/node_modules/.bin/ast-mcp", "args": [] } } }\n' > "${proj}/.mcp.json"

    rc="$(SETUP_PROJECT_DIR="${proj}" run_setup "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_file_present "${dir}/home/.local/bin/ast-mcp" "user scope still installed" || return 1
    assert_file_present "${proj}/.ast-mcp/node_modules/.bin/ast-mcp" \
        "project-local ast-mcp pre-installed so the committed .mcp.json resolves at first connect" || return 1
}

main "$@"
