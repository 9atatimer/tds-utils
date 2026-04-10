#!/bin/zsh
# 01_index_archived_logs.sh — index real archived logs and verify index is non-empty
#
# This is setup for all subsequent tests. Indexes real session logs
# from $TDS_LOG_DIR/archived/ into a temp index directory.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
source "${SCRIPT_DIR}/config.sh"

# --- Test ---

main() {
    "${LOG_INDEXER}" --index-dir "${SMOKE_INDEX_DIR}" --log-dir "${ARCHIVED_DIR}"

    if [[ -z "$(ls -A "${SMOKE_INDEX_DIR}" 2>/dev/null)" ]]; then
        print "  FAIL: index directory is empty after indexing"
        return 1
    fi
    print "  PASS: index directory is non-empty"
}

main "$@"
