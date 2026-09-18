#!/usr/bin/env bash
# smoketest_review_settled.sh -- run the review-settled unit suite and a
# --dry-run argument check of bin/review-settled (no network).
#
# Requires node >= 20 on PATH. Exit 0 = pass.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Action functions ---

run_unit_suite() {
    node --test "${REPO_ROOT}/test/review_settled.test.mjs"
}

check_usage_errors() {
    local out
    # No --repo: must fail fast with the usage reason, never touch the network.
    if out=$(GITHUB_TOKEN=x node "${REPO_ROOT}/bin/review-settled" --pr 1 2>&1); then
        echo "FAIL: bin/review-settled accepted a call without --repo" >&2
        return 1
    fi
    grep -q -- '--repo OWNER/NAME is required' <<< "$out"
    # No token: the same shape.
    if out=$(env -u GITHUB_TOKEN node "${REPO_ROOT}/bin/review-settled" --repo o/n --pr 1 2>&1); then
        echo "FAIL: bin/review-settled ran without GITHUB_TOKEN" >&2
        return 1
    fi
    grep -q 'GITHUB_TOKEN is not set' <<< "$out"
    echo "PASS: bin/review-settled usage errors"
}

# --- Flow functions ---

run_all() {
    run_unit_suite
    check_usage_errors
}

# --- Main ---

main() {
    run_all
}

main "$@"
