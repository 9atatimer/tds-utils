#!/usr/bin/env bash
# 02_opencode_enable.sh — the opencode enable hook registers ast-mcp canonically,
# preserves an unrelated mcp server, and is idempotent.
#
# Given a ~/.config/opencode/opencode.json with an unrelated mcp server, When the
# enable pre-hook runs twice, Then ast-mcp is registered as a local server with
# the canonical absolute command, the unrelated server survives, and the second
# run changes nothing (byte-identical output).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    require_hook "${OPENCODE_HOOK}" || return 1

    local home cfg
    home="$(new_home)"
    cfg="${home}/.config/opencode/opencode.json"
    write_opencode_fixture "${home}"

    # First application.
    run_opencode_hook "${home}" >/dev/null
    assert_valid_json "${cfg}" "opencode config after first run" || return 1
    cp "${cfg}" "${home}/after1.json"

    # (c) canonical local server entry: type/local, absolute command, enabled.
    assert_jq_eq "${cfg}" '.mcp["ast-mcp"].type' "local" \
        "ast-mcp type is local" || return 1
    assert_jq_eq "${cfg}" '.mcp["ast-mcp"].command | @json' "[\"$(ast_mcp_bin "${home}")\"]" \
        "ast-mcp command is the canonical absolute path" || return 1
    assert_jq_eq "${cfg}" '.mcp["ast-mcp"].enabled' "true" \
        "ast-mcp is enabled" || return 1

    # (b) unrelated server preserved.
    assert_jq_eq "${cfg}" '.mcp["existing-other"].command | @json' '["/usr/bin/other-mcp"]' \
        "unrelated mcp server preserved" || return 1

    # (a) idempotent: a second run yields byte-identical, valid JSON.
    run_opencode_hook "${home}" >/dev/null
    assert_valid_json "${cfg}" "opencode config after second run" || return 1
    assert_identical "${home}/after1.json" "${cfg}" \
        "opencode hook is idempotent across two runs" || return 1
}

main "$@"
