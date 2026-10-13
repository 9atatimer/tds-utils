#!/usr/bin/env bash
# smoketest_ocr_review.sh -- run the OCR on Demand node suites (lib/ocr-review,
# bin/ocr-review, the workflow files) and a usage check of bin/ocr-review.
# No network.
#
# Requires node >= 20 on PATH. Exit 0 = pass.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Action functions ---

run_suites() {
    node --test \
        "${REPO_ROOT}/test/ocr_review_authorize.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_gateway.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_verdict.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_record.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_io.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_workflow.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_stats.test.mjs"
}

check_usage_error() {
    local out
    # An unknown subcommand fails fast with the usage line and touches nothing.
    if out=$(node "${REPO_ROOT}/bin/ocr-review" frobnicate 2>&1); then
        echo "FAIL: bin/ocr-review accepted an unknown subcommand" >&2
        return 1
    fi
    grep -q 'usage: ocr-review' <<< "${out}"
    echo "PASS: bin/ocr-review usage error"
}

# --- Flow functions ---

run_all() {
    run_suites
    check_usage_error
}

# --- Main ---

main() {
    run_all
}

main "$@"
