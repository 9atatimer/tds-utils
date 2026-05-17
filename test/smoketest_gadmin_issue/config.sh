#!/usr/bin/env bash
# config.sh — shared environment + helpers for gadmin-issue smoke tests
#
# Hermetic: no network, no real GitHub calls. Scenarios exercise the
# pure-logic pieces (grammar round-trips, sync-plan sentinel preservation,
# migration parser). Phases that require a live GH / NATS / aggregator are
# marked SKIP and run only when the relevant tools are available.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export GADMIN_ADMIN_DIR="${REPO_DIR}/gadmin/admin"
export GADMIN_GRAMMAR="${GADMIN_ADMIN_DIR}/issue-grammar.mjs"
export GADMIN_CLIENT="${GADMIN_ADMIN_DIR}/issue-client.mjs"
export GADMIN_AGGREGATOR="${GADMIN_ADMIN_DIR}/issue-aggregator.mjs"

# --- Action helpers ----------------------------------------------------------

require_node() {
    if ! command -v node >/dev/null 2>&1; then
        echo "skip: node not on PATH" >&2
        return 1
    fi
}

# Run a node script against the in-tree gadmin/admin/ modules. Echoes stdout;
# scenario decides how to interpret it.
run_node() {
    node "$@"
}
