#!/usr/bin/env bash
# smoketest_emacs_init.sh -- verify the emacs init loads batch-mode without
# error. VERIFY gate for the emacs package: runs against the staged tree via
# TDS_VERIFY_ROOT when set (see bin/tds-install), else against this checkout.
# Skips (exit 0, loud) when no emacs binary is available -- the gate matters
# on target machines, which have emacs; CI containers may not.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"

# --- Action functions ---

find_init() {
    local root="${TDS_VERIFY_ROOT:-${REPO_DIR}}"
    printf '%s\n' "${root}/emacs/dot.emacs.d/init.el"
}

# --- Flow functions ---

run_check() {
    local init
    init="$(find_init)"
    if ! command -v emacs >/dev/null 2>&1; then
        echo "SKIP: no emacs binary on PATH (init not exercised)"
        return 0
    fi
    if [ ! -f "${init}" ]; then
        echo "FAIL: init.el not found at ${init}" >&2
        return 1
    fi
    # --batch -q loads nothing implicitly; -l loads exactly our init.
    if emacs --batch -q -l "${init}" --eval '(message "init ok")' 2>&1 | tail -1; then
        echo "PASS: init.el loaded batch-mode"
    else
        echo "FAIL: init.el errored during batch load" >&2
        return 1
    fi
}

# --- Main ---

main() { run_check; }
main "$@"
