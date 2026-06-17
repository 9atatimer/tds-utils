#!/usr/bin/env bash
# 01_sizing_picks_cheapest.sh
# Given the default 4-GPU cap, When the sizer auto-picks int4, Then it returns
# the cheapest single-node fit (4x h200) — A100 is excluded because it would
# need 8 GPUs. Raising the cap to 8 brings the cheaper 8x a100 back.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    local plan
    # Default cap (4): cheapest int4 fit is 4x h200.
    plan="$(sizing_plan int4 auto spot)"
    assert_eq "${plan}" "h200 4 4 7.08" "int4 auto pick under 4-GPU cap should be 4x h200"

    # Override the cap to 8: the cheaper 8x a100 config becomes eligible again.
    plan="$( REMVLLM_MAX_GPUS=8 bash -c '
        source "'"${LIB_DIR}"'/sizing.sh"; sizing_plan int4 auto spot' )"
    assert_eq "${plan}" "a100 8 8 5.28" "raising cap to 8 should re-admit 8x a100"
}

main "$@"
