#!/bin/zsh
# 03_semantic_match.sh — semantic search finds a session by meaning, not exact words
#
# Searches for "checking environment variables for a running service"
# and verifies the result points to the session where launchctl was used
# to inspect OLLAMA environment variables — even though the query shares
# no exact keywords with the log content.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
source "${SCRIPT_DIR}/config.sh"

# --- Test ---

main() {
    local output
    output=$("${LOG_SEARCH}" --index-dir "${SMOKE_INDEX_DIR}" "checking environment variables for a running service" 2>/dev/null)

    if [[ -z "${output}" ]]; then
        print "  FAIL: semantic search returned no results"
        return 1
    fi
    print "  PASS: search returned results"

    # The top result should point to a session containing launchctl getenv
    # (the actual command used to check env vars for the ollama service).
    local session_path
    session_path=$(print "${output}" | head -1 | cut -f1)

    if [[ ! -d "${session_path}" ]]; then
        print "  FAIL: result session path does not exist: ${session_path}"
        return 1
    fi
    print "  PASS: result session path exists"

    if ! find "${session_path}" -type f -name '*.log' -exec grep -q -l "launchctl" {} + >/dev/null 2>&1; then
        print "  FAIL: result session does not contain 'launchctl' (expected the env-check session)"
        return 1
    fi
    print "  PASS: result session contains launchctl activity"
}

main "$@"
