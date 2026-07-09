#!/usr/bin/env bash
# Given a fresh environment with no ~/.claude.json, When setup.sh runs, Then it
# installs ast-mcp at user scope (~/.local/bin/ast-mcp) and registers it in a
# newly created ~/.claude.json at that exact path (the canonical user-scope
# binary the clai hook also uses).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
: "${SMOKE_TMP:=$(mktemp -d)}"

main() {
    require_setup || return 1
    require_python3 || return 0
    local dir rc bin cfg
    dir="$(scenario_dir fresh)"
    make_npm_stub "${dir}/bin"

    rc="$(run_setup "${dir}")"
    bin="${dir}/home/.local/bin/ast-mcp"
    cfg="${dir}/home/.claude.json"

    assert_eq "${rc}" "0" "env-setup must exit 0 (fail-open)" || return 1
    assert_file_present "${bin}" "ast-mcp bin installed at user scope" || return 1
    assert_file_present "${cfg}" "~/.claude.json created" || return 1
    assert_json_eq "${cfg}" "d['mcpServers']['ast-mcp']['command']" "${bin}" \
        "~/.claude.json registers ast-mcp at the installed user-scope bin path" || return 1
}

main "$@"
