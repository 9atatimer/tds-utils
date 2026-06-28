#!/usr/bin/env bash
# 01_claude_enable.sh — the claude enable hook registers ast-mcp canonically,
# preserves unrelated state, clears stale disables, and is idempotent.
#
# Given a ~/.claude.json with an unrelated mcp server and projects that disable
# ast-mcp, When the enable pre-hook runs twice, Then ast-mcp is registered with
# the canonical absolute command, the unrelated server and top-level keys
# survive, ast-mcp is no longer disabled in any project, and the second run
# changes nothing (byte-identical output).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    require_hook "${CLAUDE_HOOK}" || return 1

    local home cfg
    home="$(new_home)"
    cfg="${home}/.claude.json"
    write_claude_fixture "${home}"

    # First application.
    run_claude_hook "${home}" >/dev/null
    assert_valid_json "${cfg}" "claude config after first run" || return 1
    cp "${cfg}" "${home}/after1.json"

    # (c) ast-mcp registered with the canonical absolute command and empty args.
    assert_jq_eq "${cfg}" '.mcpServers["ast-mcp"].command' "${AST_MCP_BIN}" \
        "ast-mcp command is the canonical absolute path" || return 1
    assert_jq_eq "${cfg}" '.mcpServers["ast-mcp"].args | length' "0" \
        "ast-mcp args is empty" || return 1

    # (b) unrelated server and unrelated top-level key preserved.
    assert_jq_eq "${cfg}" '.mcpServers["existing-other"].command' "/usr/bin/other-mcp" \
        "unrelated mcp server preserved" || return 1
    assert_jq_eq "${cfg}" '.numStartups' "7" \
        "unrelated top-level key preserved" || return 1

    # ast-mcp un-disabled in every project; sibling disables left untouched.
    assert_jq_eq "${cfg}" '[.projects[]?.disabledMcpServers[]?] | any(. == "ast-mcp")' "false" \
        "ast-mcp removed from every disabledMcpServers" || return 1
    assert_jq_eq "${cfg}" '.projects["/Users/stumpf/proj-a"].disabledMcpServers | @json' '["cloudflare"]' \
        "sibling disabled servers preserved" || return 1

    # (a) idempotent: a second run yields byte-identical, valid JSON.
    run_claude_hook "${home}" >/dev/null
    assert_valid_json "${cfg}" "claude config after second run" || return 1
    assert_identical "${home}/after1.json" "${cfg}" \
        "claude hook is idempotent across two runs" || return 1
}

main "$@"
