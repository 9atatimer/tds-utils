#!/usr/bin/env bash
# 04_state_roundtrip.sh
# Given a written state record, When read back, Then strings/numbers/booleans
# round-trip and state_has_instance / state_clear behave.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    if ! command -v jq >/dev/null 2>&1; then
        echo "skip: jq not on PATH"
        return 0
    fi

    # Global (not local) so the EXIT trap can see it after main returns.
    base="$(mktemp -d)"
    trap 'rm -rf "${base}"' EXIT
    export REMVLLM_FAKE_HOSTNAME="testhost"

    # Absent before any write.
    assert_fails state_has_instance "${base}"

    state_write "${base}" \
        instance_id="spheron-abc123" gpu_type="a100" gpu_count=8 \
        spot=true est_cost_hr=5.28 recipe="glm-5.2"

    state_has_instance "${base}" || { echo "FAIL: instance should exist"; return 1; }
    assert_eq "$(state_read "${base}" instance_id)" "spheron-abc123" "string field"
    assert_eq "$(state_read "${base}" gpu_count)"   "8"              "number field"
    assert_eq "$(state_read "${base}" spot)"        "true"           "boolean field"
    assert_eq "$(state_read "${base}" est_cost_hr)" "5.28"           "float field"
    assert_eq "$(state_read "${base}" missing)"     ""               "absent field is empty"

    state_clear "${base}"
    assert_fails state_has_instance "${base}"
}

main "$@"
