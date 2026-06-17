#!/usr/bin/env bash
# 05_modelcache_uri.sh
# Given a model id, When addressing the bucket cache, Then the key is sanitized
# and the URI is namespaced by quant (so HF is only ever a fallback).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    assert_eq "$(modelcache_key 'zai-org/GLM-5.2')" \
        "zai-org__GLM-5.2" "slash should be sanitized to __"

    assert_eq "$(modelcache_uri 'r2:remvllm-weights' 'zai-org/GLM-5.2')" \
        "r2:remvllm-weights/models/zai-org__GLM-5.2" "base uri"

    assert_eq "$(modelcache_uri 'r2:remvllm-weights' 'zai-org/GLM-5.2' 'int4')" \
        "r2:remvllm-weights/models/zai-org__GLM-5.2/int4" "quant-namespaced uri"

    # Trailing slash on the bucket URL must not double up.
    assert_eq "$(modelcache_uri 'r2:remvllm-weights/' 'zai-org/GLM-5.2')" \
        "r2:remvllm-weights/models/zai-org__GLM-5.2" "trailing slash normalized"
}

main "$@"
