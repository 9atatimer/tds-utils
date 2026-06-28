#!/usr/bin/env bash
# config.sh — shared fixtures + helpers for the clai ast-mcp enable-hook tests
#
# Network-free and hermetic. Every scenario runs a clai pre-hook against a
# throwaway $HOME populated with fixture agent configs, so no real user config
# is ever read or written. Sourcing this file is side-effect-free; run_all.sh
# allocates ${SMOKE_TMP} and each scenario calls `new_home` to mint an isolated
# fake HOME beneath it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Hooks under test (clai pre-stage wiring for the four clai agents).
# Overridable via the environment so the suite can be aimed at a staged copy.
: "${CLAUDE_HOOK:=${REPO_DIR}/clai.d/claude/pre/20-enable-ast-mcp}"
: "${OPENCODE_HOOK:=${REPO_DIR}/clai.d/opencode/pre/20-enable-ast-mcp}"
: "${AGY_HOOK:=${REPO_DIR}/clai.d/agy/pre/20-enable-ast-mcp}"
: "${CODEX_HOOK:=${REPO_DIR}/clai.d/codex/pre/20-enable-ast-mcp}"

# The hooks write ${HOME}/.local/bin/ast-mcp -- expanded against the HOME the
# hook ran under, i.e. a per-user literal absolute path (GUI-safe). Scenarios
# derive the expected command from their own fake HOME via this helper rather
# than baking in a specific username.
ast_mcp_bin() { printf '%s/.local/bin/ast-mcp' "$1"; }

# --- Guards ------------------------------------------------------------------

# jq is the tool the hooks (and these assertions) rely on; skip the suite if
# it is unavailable rather than reporting spurious failures.
require_jq() {
    command -v jq >/dev/null 2>&1 || {
        echo "skip: jq not on PATH (required by the hooks under test)" >&2
        return 1
    }
}

# A clai pre-hook must exist and be executable per the hook contract.
require_hook() {
    local hook="$1"
    [[ -x "${hook}" ]] || {
        echo "FAIL: hook not found or not executable: ${hook}"
        return 1
    }
}

# --- Fixture HOME ------------------------------------------------------------

# Mint a fresh, isolated fake HOME under SMOKE_TMP and echo its path.
new_home() {
    if [[ -z "${SMOKE_TMP:-}" ]]; then
        echo "error: SMOKE_TMP must be set before new_home" >&2
        return 1
    fi
    local home
    home="$(mktemp -d "${SMOKE_TMP}/home.XXXXXX")"
    printf '%s\n' "${home}"
}

# Write a ~/.claude.json fixture with an unrelated mcp server, an unrelated
# top-level key, and projects that (wrongly) disable ast-mcp for the hook to fix.
write_claude_fixture() {
    local home="$1"
    cat > "${home}/.claude.json" <<JSON
{
  "numStartups": 7,
  "mcpServers": {
    "existing-other": { "command": "/usr/bin/other-mcp", "args": ["--foo"] }
  },
  "projects": {
    "/Users/stumpf/proj-a": { "disabledMcpServers": ["ast-mcp", "cloudflare"] },
    "/Users/stumpf/proj-b": { "disabledMcpServers": ["cloudflare"] }
  }
}
JSON
}

# Write a ~/.config/opencode/opencode.json fixture with an unrelated mcp server.
write_opencode_fixture() {
    local home="$1"
    mkdir -p "${home}/.config/opencode"
    cat > "${home}/.config/opencode/opencode.json" <<JSON
{
  "\$schema": "https://opencode.ai/config.json",
  "mcp": {
    "existing-other": { "type": "local", "command": ["/usr/bin/other-mcp"], "enabled": true }
  }
}
JSON
}

# Write a minimal opencode config with NO .mcp key (exercise create-if-absent).
write_opencode_fixture_no_mcp() {
    local home="$1"
    mkdir -p "${home}/.config/opencode"
    cat > "${home}/.config/opencode/opencode.json" <<JSON
{ "\$schema": "https://opencode.ai/config.json", "theme": "system" }
JSON
}

# Write a ~/.gemini/config/mcp_config.json fixture (agy/Antigravity reads this
# shared codeium-format file) with an unrelated mcp server.
write_agy_fixture() {
    local home="$1"
    mkdir -p "${home}/.gemini/config"
    cat > "${home}/.gemini/config/mcp_config.json" <<JSON
{
  "mcpServers": {
    "emacs": { "command": "socat", "args": ["-", "UNIX-CONNECT:/tmp/emacs.sock"] }
  }
}
JSON
}

# Write a ~/.codex/config.toml fixture with an unrelated top-level key and an
# unrelated [mcp_servers.*] table (the codex hook appends to this file).
write_codex_fixture() {
    local home="$1"
    mkdir -p "${home}/.codex"
    cat > "${home}/.codex/config.toml" <<'TOML'
model = "gpt-5-codex"

[mcp_servers.node_repl]
command = "node"
args = ["--experimental-repl-await"]
TOML
}

# --- Hook runners ------------------------------------------------------------

# Run a clai pre-hook with a hermetic environment rooted at the fake HOME.
# XDG_CONFIG_HOME is pinned beneath the fake HOME so that a stray value in the
# caller's environment can never redirect the hook at the real user config.
run_hook() {
    local home="$1" agent="$2" hook="$3"
    HOME="${home}" \
    XDG_CONFIG_HOME="${home}/.config" \
    CLAI_AGENT="${agent}" \
    CLAI_CWD="${home}" \
    CLAI_STAGE="pre" \
    CLAI_ARGS="" \
        bash "${hook}"
}

run_claude_hook()   { run_hook "$1" claude   "${CLAUDE_HOOK}"; }
run_opencode_hook() { run_hook "$1" opencode "${OPENCODE_HOOK}"; }
run_agy_hook()      { run_hook "$1" agy      "${AGY_HOOK}"; }
run_codex_hook()    { run_hook "$1" codex    "${CODEX_HOOK}"; }

# --- Assertions --------------------------------------------------------------

# Assert two files are byte-identical (the hallmark of an idempotent write).
assert_identical() {
    local a="$1" b="$2" msg="$3"
    if ! cmp -s "${a}" "${b}"; then
        echo "FAIL: ${msg} (files differ)"
        echo "--- first ---";  cat "${a}"
        echo "--- second ---"; cat "${b}"
        return 1
    fi
}

# Assert a file parses as valid JSON.
assert_valid_json() {
    local f="$1" msg="$2"
    if ! jq empty "${f}" >/dev/null 2>&1; then
        echo "FAIL: ${msg} (not valid JSON): ${f}"
        cat "${f}"
        return 1
    fi
}

# Assert `jq -r <filter>` over a file equals an expected string.
assert_jq_eq() {
    local f="$1" filter="$2" expected="$3" msg="$4"
    local got
    got="$(jq -r "${filter}" "${f}")"
    if [[ "${got}" != "${expected}" ]]; then
        echo "FAIL: ${msg}"
        echo "  filter:   ${filter}"
        echo "  expected: ${expected}"
        echo "  got:      ${got}"
        return 1
    fi
}

export -f require_jq require_hook new_home ast_mcp_bin \
    write_claude_fixture write_opencode_fixture write_opencode_fixture_no_mcp \
    write_agy_fixture write_codex_fixture \
    run_hook run_claude_hook run_opencode_hook run_agy_hook run_codex_hook \
    assert_identical assert_valid_json assert_jq_eq
