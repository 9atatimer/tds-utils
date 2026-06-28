#!/usr/bin/env bash
# healthcheck.sh -- Reports liveness of each pinned LMDE MCP server.
#
# For every server in servers.txt, verifies the $HOME/.local/bin symlink exists
# and the MCP initialize handshake succeeds. Prints one line per server and
# exits non-zero if any server is degraded.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVERS_FILE="${SCRIPT_DIR}/servers.txt"

# shellcheck source=lib.sh disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

# --- Action functions ---

# check_one <name> <bin> -- print status for a single server; return 0 if OK,
# 1 if degraded.
check_one() {
    local name="$1"
    local bin="$2"
    local link="${MCP_BIN_DIR}/${bin}"

    if [[ ! -e "${link}" ]]; then
        echo "${name}: DEGRADED (missing symlink ${link})"
        return 1
    fi
    if ! healthcheck_server "${name}" "${bin}"; then
        echo "${name}: DEGRADED (initialize handshake failed)"
        return 1
    fi
    echo "${name}: OK"
    return 0
}

# --- Flow functions ---

run_healthcheck() {
    if [[ ! -f "${SERVERS_FILE}" ]]; then
        echo "ERROR: manifest not found at ${SERVERS_FILE}" >&2
        exit 1
    fi

    local degraded=0
    local name version tag repo bin
    while read -r name version tag repo bin _ || [[ -n "${name}" ]]; do
        [[ "${name}" =~ ^#.*$ ]] && continue
        [[ -z "${name}" ]] && continue
        check_one "${name}" "${bin}" || degraded=1
    done < "${SERVERS_FILE}"

    return "${degraded}"
}

# --- Main ---

main() {
    run_healthcheck
}

main "$@"
