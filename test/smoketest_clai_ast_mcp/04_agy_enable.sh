#!/usr/bin/env bash
# 04_agy_enable.sh — the agy (Antigravity CLI) enable hook registers ast-mcp
# canonically, preserves unrelated mcpServers, and is idempotent.
#
# Given a ~/.gemini/config/mcp_config.json with an unrelated server, When the
# enable pre-hook runs twice, Then ast-mcp is registered with the canonical
# absolute command, the unrelated server survives, and the second run changes
# nothing (byte-identical output).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    require_hook "${AGY_HOOK}" || return 1

    local home cfg
    home="$(new_home)"
    cfg="${home}/.gemini/config/mcp_config.json"
    write_agy_fixture "${home}"

    # First application.
    run_agy_hook "${home}" >/dev/null
    assert_valid_json "${cfg}" "agy config after first run" || return 1
    cp "${cfg}" "${home}/after1.json"

    # ast-mcp registered with the canonical absolute command and empty args.
    assert_jq_eq "${cfg}" '.mcpServers["ast-mcp"].command' "${AST_MCP_BIN}" \
        "ast-mcp command is the canonical absolute path" || return 1
    assert_jq_eq "${cfg}" '.mcpServers["ast-mcp"].args | length' "0" \
        "ast-mcp args is empty" || return 1

    # Unrelated server preserved.
    assert_jq_eq "${cfg}" '.mcpServers["emacs"].command' "socat" \
        "unrelated mcp server preserved" || return 1

    # Idempotent: a second run yields byte-identical, valid JSON.
    run_agy_hook "${home}" >/dev/null
    assert_valid_json "${cfg}" "agy config after second run" || return 1
    assert_identical "${home}/after1.json" "${cfg}" \
        "agy hook is idempotent across two runs" || return 1
}

main "$@"
