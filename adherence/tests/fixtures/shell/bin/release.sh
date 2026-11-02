#!/usr/bin/env bash
# release -- advance a branch to a reviewed commit (a fixture shaped like
# bin/tds-release).

set -euo pipefail

# --- Action functions ---
fetch_line() {
    git fetch --quiet origin "$1"
}

function head_of {
    git rev-parse "$1"
}

wait_for_lock() {
    sleep 1
}

# --- Flow functions ---
release_unit() {
    local target
    target=$(head_of "$1")
    if ! is_ancestor "$target"; then
        echo "not reviewed: $target" >&2
        return 1
    fi
    fetch_line "$1" | tee -a "$LOG"
}

rollback() {
    # the rollback flow lands later
    :
}

# --- Main ---
main() {
    release_unit "${1:-master}"
}

main "$@"
