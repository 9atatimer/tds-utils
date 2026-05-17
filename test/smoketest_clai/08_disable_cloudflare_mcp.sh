#!/usr/bin/env bash
# 08_disable_cloudflare_mcp.sh
# Given a fresh ~/.claude.json with no entry for $PWD and the real
# 10-disable-cloudflare-mcp hook installed, when clai runs, then the hook
# adds the configured server names to disabledMcpServers for $PWD.
# Re-running is idempotent (no duplicates) and respects pre-existing entries
# (no removals).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    if ! command -v jq >/dev/null 2>&1; then
        echo "skip: jq not on PATH" >&2; return 0
    fi
    init_scenario "08_cloudflare"

    # Symlink the real hook + conf into the fake HOME's clai.d.
    local real_hook_dir="${REPO_DIR}/clai.d/claude/pre"
    local fake_pre="${FAKE_HOME}/clai.d/claude/pre"
    mkdir -p "${fake_pre}"
    ln -s "${real_hook_dir}/10-disable-cloudflare-mcp" "${fake_pre}/10-disable-cloudflare-mcp"
    ln -s "${real_hook_dir}/10-disable-cloudflare-mcp.conf" "${fake_pre}/10-disable-cloudflare-mcp.conf"

    # Seed ~/.claude.json with an unrelated project entry that has a pre-existing
    # disabledMcpServers value (must be preserved).
    cat > "${FAKE_HOME}/.claude.json" <<EOF
{
  "mcpServers": {},
  "projects": {
    "/some/other/project": {
      "disabledMcpServers": ["pre-existing-entry"]
    }
  }
}
EOF

    make_agent claude 0
    run_clai proj claude >/dev/null

    local proj_real
    proj_real="$(cd "${FAKE_HOME}/proj" && pwd -P)"

    # The CWD entry should now contain all configured names.
    local got_added
    got_added="$(jq --arg k "${proj_real}" '.projects[$k].disabledMcpServers' "${FAKE_HOME}/.claude.json")"
    for name in cloudflare-graphql cloudflare-casb cloudflare-bindings cloudflare-audit; do
        if ! jq -e --arg n "${name}" '. | index($n)' <<<"${got_added}" >/dev/null; then
            echo "FAIL: ${name} missing from disabledMcpServers" >&2
            echo "got: ${got_added}" >&2; return 1
        fi
    done

    # Pre-existing entry on the unrelated project must be preserved.
    local preserved
    preserved="$(jq -r '.projects["/some/other/project"].disabledMcpServers[0]' "${FAKE_HOME}/.claude.json")"
    if [[ "${preserved}" != "pre-existing-entry" ]]; then
        echo "FAIL: pre-existing entry on unrelated project was clobbered" >&2; return 1
    fi

    # Idempotency: second run must not duplicate.
    run_clai proj claude >/dev/null
    local count
    count="$(jq --arg k "${proj_real}" '.projects[$k].disabledMcpServers | length' "${FAKE_HOME}/.claude.json")"
    if (( count != 4 )); then
        echo "FAIL: idempotency broken, count=${count}" >&2; return 1
    fi
}

main "$@"
