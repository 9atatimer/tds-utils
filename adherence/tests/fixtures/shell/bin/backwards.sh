#!/usr/bin/env bash
# backwards -- a tool whose entry point sits above the functions it calls,
# out of the file-anatomy order.

set -euo pipefail

# --- Main ---
main() {
    greet "$@"
}

# --- Action functions ---
greet() {
    echo "hello, ${1:-world}"
}

main "$@"
