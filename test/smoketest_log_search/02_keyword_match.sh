#!/bin/zsh
# 02_keyword_match.sh — keyword search returns a session containing that keyword
#
# Searches for "ollama" and verifies the result points to a session
# whose log files actually contain the word "ollama".

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
source "${SCRIPT_DIR}/config.sh"

# --- Test ---

main() {
    local output
    output=$("${LOG_SEARCH}" --index-dir "${SMOKE_INDEX_DIR}" "ollama" 2>/dev/null)

    if [[ -z "${output}" ]]; then
        print "  FAIL: search for 'ollama' returned no results"
        return 1
    fi
    print "  PASS: search returned results"

    # Extract the first result's session path (first tab-delimited field).
    local session_path
    session_path=$(print "${output}" | head -1 | cut -f1)

    if [[ ! -d "${session_path}" ]]; then
        print "  FAIL: result session path does not exist: ${session_path}"
        return 1
    fi
    print "  PASS: result session path exists"

    if ! find "${session_path}" -type f -name '*.log' -exec grep -q "ollama" {} + 2>/dev/null; then
        print "  FAIL: result session does not actually contain 'ollama'"
        return 1
    fi
    print "  PASS: result session actually contains 'ollama'"
}

main "$@"
