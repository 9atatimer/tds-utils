#!/usr/bin/env bash
# config.sh — shared environment + helpers for remvllm smoke tests.
#
# Hermetic: pure-logic libs only (sizing, state, modelcache, config). No network,
# no cloud, no op/terraform/ssh. Sourcing is side-effect-free; each scenario
# sources this file, then asserts behavior through the public lib functions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LIB_DIR="${REPO_DIR}/ops/terraform/remvllm/lib"

# shellcheck source=../../ops/terraform/remvllm/lib/sizing.sh
source "${LIB_DIR}/sizing.sh"
# shellcheck source=../../ops/terraform/remvllm/lib/state.sh
source "${LIB_DIR}/state.sh"
# shellcheck source=../../ops/terraform/remvllm/lib/modelcache.sh
source "${LIB_DIR}/modelcache.sh"
# shellcheck source=../../ops/terraform/remvllm/lib/config.sh
source "${LIB_DIR}/config.sh"

# --- Assertion helpers -------------------------------------------------------

assert_eq() {
    local got="$1" want="$2" msg="${3:-}"
    if [[ "${got}" != "${want}" ]]; then
        echo "FAIL: ${msg}"
        echo "  got:  '${got}'"
        echo "  want: '${want}'"
        return 1
    fi
}

# Run a command expected to FAIL (non-zero). Fails the test if it succeeds.
assert_fails() {
    if "$@" >/dev/null 2>&1; then
        echo "FAIL: expected non-zero exit from: $*"
        return 1
    fi
}
