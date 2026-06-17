#!/usr/bin/env bash
# 02_sizing_respects_flags.sh
# Given an explicit --gpu, When it can fit the quant, Then the sizer uses it;
# When it cannot (fp8 on a100, 8x80GB < 860GB), Then the sizer REJECTS it.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    # int4 on h200 fits at TP 4.
    local plan
    plan="$(sizing_plan int4 h200 spot)"
    assert_eq "${plan}" "h200 4 4 7.08" "int4 on h200 should size to 4 GPUs"

    # fp8 does not fit on any valid a100 count -> must fail loudly.
    assert_fails sizing_plan fp8 a100 spot

    # The underlying capacity check also rejects it.
    assert_fails sizing_gpu_count fp8 a100
}

main "$@"
