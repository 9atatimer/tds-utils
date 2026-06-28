#!/usr/bin/env bash
# 03_opencode_creates_mcp.sh — the opencode enable hook creates the .mcp object
# when the config lacks one, without disturbing unrelated keys.
#
# Given a ~/.config/opencode/opencode.json with no .mcp key, When the enable
# pre-hook runs twice, Then a .mcp object is created containing the canonical
# ast-mcp entry, the unrelated top-level key survives, and the second run
# changes nothing (byte-identical output).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    require_hook "${OPENCODE_HOOK}" || return 1

    local home cfg
    home="$(new_home)"
    cfg="${home}/.config/opencode/opencode.json"
    write_opencode_fixture_no_mcp "${home}"

    # First application.
    run_opencode_hook "${home}" >/dev/null
    assert_valid_json "${cfg}" "opencode config after first run" || return 1
    cp "${cfg}" "${home}/after1.json"

    # (c) .mcp created with the canonical ast-mcp local server entry.
    assert_jq_eq "${cfg}" '.mcp["ast-mcp"].command | @json' "[\"$(ast_mcp_bin "${home}")\"]" \
        "ast-mcp command is the canonical absolute path" || return 1
    assert_jq_eq "${cfg}" '.mcp["ast-mcp"].type' "local" \
        "ast-mcp type is local" || return 1

    # (b) unrelated top-level key preserved.
    assert_jq_eq "${cfg}" '.theme' "system" \
        "unrelated top-level key preserved" || return 1

    # (a) idempotent: a second run yields byte-identical, valid JSON.
    run_opencode_hook "${home}" >/dev/null
    assert_valid_json "${cfg}" "opencode config after second run" || return 1
    assert_identical "${home}/after1.json" "${cfg}" \
        "opencode hook is idempotent across two runs" || return 1
}

main "$@"
