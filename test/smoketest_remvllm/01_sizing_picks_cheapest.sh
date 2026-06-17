#!/usr/bin/env bash
# 01_sizing_picks_cheapest.sh
# Given quant int4 (the cheap default), When the sizer auto-picks, Then it
# returns the lowest-cost spot config that fits (8x a100). For fp8 the cheapest
# fit is 8x h200.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    local plan
    plan="$(sizing_plan int4 auto spot)"
    assert_eq "${plan}" "a100 8 8 5.28" "int4 auto pick should be cheapest spot fit"

    plan="$(sizing_plan fp8 auto spot)"
    assert_eq "${plan}" "h200 8 8 14.16" "fp8 auto pick should be cheapest fp8 fit"
}

main "$@"
