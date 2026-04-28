#!/usr/bin/env bash
# 06_org_filter.sh — --exclude-org hides matching repos (G7).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    make_fake_clone "alpha/keep" >/dev/null
    make_fake_clone "beta/drop" >/dev/null
    out="$(run_goldfish --exclude-org beta --refresh 2>/dev/null)"
    if ! grep -q "alpha/keep" <<<"${out}"; then
        echo "FAIL: alpha/keep should be visible:"
        echo "${out}"
        return 1
    fi
    if grep -q "beta/drop" <<<"${out}"; then
        echo "FAIL: beta/drop should be hidden by --exclude-org beta:"
        echo "${out}"
        return 1
    fi
    # Now check --include-org alpha keeps only alpha.
    out="$(run_goldfish --include-org alpha --refresh 2>/dev/null)"
    if ! grep -q "alpha/keep" <<<"${out}"; then
        echo "FAIL: alpha/keep should be visible with --include-org alpha:"
        echo "${out}"
        return 1
    fi
    if grep -q "beta/drop" <<<"${out}"; then
        echo "FAIL: beta/drop should be hidden by --include-org alpha:"
        echo "${out}"
        return 1
    fi
}

main "$@"
