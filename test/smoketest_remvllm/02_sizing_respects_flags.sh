#!/usr/bin/env bash
# 02_sizing_respects_flags.sh
# The GPU cap and explicit flags constrain the sizer:
#  - int4 on h200 fits in 4 GPUs (the target platform);
#  - int4 on a100 is REJECTED under the default cap (needs 8, over the cap);
#  - fp8 GLM-5.2 is REJECTED under the default cap (needs 8 of anything), but
#    fits 8x h200 once the cap is raised;
#  - fp8 on a100 never fits, cap or no cap.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    # int4 on h200 fits at TP 4 — the single-node sweet spot.
    local plan
    plan="$(sizing_plan int4 h200 spot)"
    assert_eq "${plan}" "h200 4 4 7.08" "int4 on h200 should size to 4 GPUs"

    # int4 on a100 needs 8 GPUs -> over the default 4-GPU cap -> rejected.
    assert_fails sizing_plan int4 a100 spot

    # fp8 needs ~860 GB (8 GPUs) -> over the default cap -> rejected.
    assert_fails sizing_plan fp8 auto spot

    # Raising the cap to 8 lets fp8 land on 8x h200.
    plan="$( REMVLLM_MAX_GPUS=8 bash -c '
        source "'"${LIB_DIR}"'/sizing.sh"; sizing_plan fp8 auto spot' )"
    assert_eq "${plan}" "h200 8 8 14.16" "fp8 should fit 8x h200 once cap is raised"

    # fp8 never fits on a100 (8x80=640 < 860), even with the cap raised.
    assert_fails env REMVLLM_MAX_GPUS=8 bash -c '
        source "'"${LIB_DIR}"'/sizing.sh"; sizing_gpu_count fp8 a100'
}

main "$@"
