#!/usr/bin/env bash
# setup.sh -- Installs the pinned LMDE MCP servers and registers Claude Desktop.
#
# LMDE owns INSTALL (download/install/symlink/healthcheck) and Claude DESKTOP
# registration only. Wiring for the four clai agents (claude/codex/opencode/
# agy) is handled by clai pre-hooks at agent launch, NOT here.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVERS_FILE="${SCRIPT_DIR}/servers.txt"

# shellcheck source=lib.sh disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

# --- Flow functions ---

# install_servers -- read the manifest and install/healthcheck/register each
# server. Fails loudly and exits non-zero if any server is unhealthy.
install_servers() {
    if [[ ! -f "${SERVERS_FILE}" ]]; then
        log "ERROR: manifest not found at ${SERVERS_FILE}"
        exit 1
    fi

    local name version tag repo bin
    while read -r name version tag repo bin _ || [[ -n "${name}" ]]; do
        # Skip comments and blank lines.
        [[ "${name}" =~ ^#.*$ ]] && continue
        [[ -z "${name}" ]] && continue

        log "Processing ${name} ${version} (${tag}) from ${repo}..."
        install_one_server "${name}" "${version}" "${tag}" "${repo}" "${bin}"

        log "Health-checking ${name} via handshake..."
        if ! healthcheck_server "${name}" "${bin}"; then
            log "FATAL: ${name} failed the initialize handshake; aborting." >&2
            exit 1
        fi
        log "${name}: healthy."

        log "Registering ${name} in Claude Desktop..."
        register_claude_desktop "${name}" "${bin}"
    done < "${SERVERS_FILE}"
}

print_closing_note() {
    log "MCP setup complete."
    cat <<'EOF'

  NEXT STEPS
  ----------
  * Claude Desktop: RESTART the app to pick up the new MCP server entry.
  * clai agents (claude code / codex / opencode / agy): no action needed --
    they auto-wire ast-mcp on their NEXT launch via the clai pre-hooks.
EOF
}

# --- Main ---

main() {
    install_servers
    print_closing_note
}

main "$@"
