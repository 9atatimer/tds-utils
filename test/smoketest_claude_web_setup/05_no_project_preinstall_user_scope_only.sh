#!/usr/bin/env bash
# Given a reachable repo checkout carrying a committed .mcp.json, When setup.sh
# runs, Then it installs and registers ONLY the user-scope ast-mcp and creates
# NO project-local .ast-mcp tree.
#
# This inverts the pre-#110 expectation. The committed .mcp.json now names
# "${HOME}/.local/bin/ast-mcp" -- the very binary user scope installs -- so a
# second, project-local copy buys nothing and costs two failure modes plus a
# permanent [Conflicting scopes] diagnostic (user and project naming different
# endpoints). One binary, one path, both scopes resolving to it.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    require_python3 || return 0
    local dir rc proj
    dir="$(scenario_dir project)"
    make_npm_stub "${dir}/bin"
    # A fixture "checkout" with a committed .mcp.json naming the user-scope bin.
    proj="${dir}/checkout"
    mkdir -p "${proj}"
    printf '{ "mcpServers": { "ast-mcp": { "command": "${HOME}/.local/bin/ast-mcp", "args": [] } } }\n' > "${proj}/.mcp.json"

    rc="$(SETUP_PROJECT_DIR="${proj}" run_setup "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_file_present "${dir}/home/.local/bin/ast-mcp" "user scope installed" || return 1
    assert_file_absent "${proj}/.ast-mcp/node_modules/.bin/ast-mcp" \
        "no project-local ast-mcp: the committed .mcp.json points at the user-scope binary" || return 1
    assert_file_absent "${proj}/.ast-mcp" \
        "no project-local .ast-mcp tree is created at all" || return 1
}

main "$@"
