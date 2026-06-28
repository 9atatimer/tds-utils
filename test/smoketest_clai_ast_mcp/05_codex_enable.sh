#!/usr/bin/env bash
# 05_codex_enable.sh — the codex enable hook appends an [mcp_servers.ast-mcp]
# table canonically, preserves unrelated TOML, and is idempotent (append-only
# must not duplicate the block).
#
# Given a ~/.codex/config.toml with an unrelated top-level key and an unrelated
# [mcp_servers.*] table, When the enable pre-hook runs twice, Then ast-mcp is
# registered with the canonical absolute command, the unrelated key and table
# survive, the block appears exactly once, and the second run changes nothing.
#
# Skips (PASS) when python3 is unavailable -- the hook itself no-ops there, so
# there is nothing to assert.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

# assert_codex_toml <file> <expected-command> -- validate the parsed TOML via
# python3/tomllib; exit non-zero (with a message) on any mismatch.
assert_codex_toml() {
    local file="$1" expected="$2"
    python3 - "${file}" "${expected}" <<'PY'
import sys, tomllib
path, expected = sys.argv[1], sys.argv[2]
with open(path, "rb") as f:
    data = tomllib.load(f)
servers = data.get("mcp_servers", {})
ok = True
def check(cond, msg):
    global ok
    if not cond:
        print(f"FAIL: {msg}"); ok = False
check(data.get("model") == "gpt-5-codex", "unrelated top-level key 'model' preserved")
check("node_repl" in servers, "unrelated [mcp_servers.node_repl] table preserved")
ast = servers.get("ast-mcp", {})
check(ast.get("command") == expected, f"ast-mcp command is the canonical path ({expected})")
check(ast.get("args") == [], "ast-mcp args is empty")
sys.exit(0 if ok else 1)
PY
}

main() {
    require_hook "${CODEX_HOOK}" || return 1

    # The codex hook no-ops (and so this scenario has nothing to assert) unless
    # python3 has stdlib tomllib, i.e. Python >= 3.11. Skip otherwise, matching
    # the hook's documented behaviour.
    if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import tomllib' 2>/dev/null; then
        echo "skip: python3 with stdlib tomllib (>= 3.11) required by the codex hook"
        return 0
    fi

    local home cfg
    home="$(new_home)"
    cfg="${home}/.codex/config.toml"
    write_codex_fixture "${home}"

    # First application.
    run_codex_hook "${home}" >/dev/null
    assert_codex_toml "${cfg}" "$(ast_mcp_bin "${home}")" || return 1
    cp "${cfg}" "${home}/after1.toml"

    # The appended table appears exactly once.
    local blocks
    blocks="$(grep -c '^\[mcp_servers\.ast-mcp\]' "${cfg}")"
    [[ "${blocks}" -eq 1 ]] || {
        echo "FAIL: expected exactly one [mcp_servers.ast-mcp] block, found ${blocks}"
        return 1
    }

    # Idempotent: a second run must not append a duplicate block.
    run_codex_hook "${home}" >/dev/null
    assert_identical "${home}/after1.toml" "${cfg}" \
        "codex hook is idempotent across two runs" || return 1
}

main "$@"
