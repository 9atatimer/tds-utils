#!/usr/bin/env bash
# Given an existing ~/.claude.json with an unrelated mcp server, an unrelated
# top-level key, and projects that disable ast-mcp, When setup.sh runs, Then it
# adds ast-mcp, preserves the unrelated server + key, and removes "ast-mcp" from
# every project's disabledMcpServers (enabled everywhere), touching nothing else.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
: "${SMOKE_TMP:=$(mktemp -d)}"

main() {
    require_setup || return 1
    require_python3 || return 0
    local dir rc cfg
    dir="$(scenario_dir preserve)"
    make_npm_stub "${dir}/bin"
    write_claude_fixture "${dir}/home"

    rc="$(run_setup "${dir}")"
    cfg="${dir}/home/.claude.json"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_json_eq "${cfg}" "d['mcpServers']['ast-mcp']['command']" "${dir}/home/.local/bin/ast-mcp" \
        "ast-mcp registered" || return 1
    assert_json_eq "${cfg}" "d['mcpServers']['existing-other']['command']" "/usr/bin/other-mcp" \
        "unrelated mcp server preserved" || return 1
    assert_json_eq "${cfg}" "d['numStartups']" "7" "unrelated top-level key preserved" || return 1
    assert_json_eq "${cfg}" "'ast-mcp' in d['projects']['/repo/a']['disabledMcpServers']" "False" \
        "ast-mcp cleared from project a's disabled list" || return 1
    assert_json_eq "${cfg}" "'cloudflare' in d['projects']['/repo/a']['disabledMcpServers']" "True" \
        "unrelated disabled entry preserved" || return 1
}

main "$@"
