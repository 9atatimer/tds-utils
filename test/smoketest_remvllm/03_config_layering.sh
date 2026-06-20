#!/usr/bin/env bash
# 03_config_layering.sh
# Given defaults in remvllm.conf and overrides in remvllm.local.conf and the
# environment, When config_load runs, Then precedence is conf < local < env.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    # Global (not local) so the EXIT trap can see it after main returns.
    tmp="$(mktemp -d)"
    trap 'rm -rf "${tmp}"' EXIT

    cat > "${tmp}/remvllm.conf" <<'EOF'
REMVLLM_QUANT=int4
REMVLLM_TTL_MINUTES=20
REMVLLM_GPU_TYPE=auto
EOF
    cat > "${tmp}/remvllm.local.conf" <<'EOF'
REMVLLM_QUANT=fp8
EOF

    # Environment override (highest precedence).
    export REMVLLM_TTL_MINUTES=99

    config_load "${tmp}"

    assert_eq "${REMVLLM_QUANT}" "fp8" "local.conf should override conf"
    assert_eq "${REMVLLM_TTL_MINUTES}" "99" "environment should override both files"
    assert_eq "${REMVLLM_GPU_TYPE}" "auto" "unoverridden default should survive"
}

main "$@"
