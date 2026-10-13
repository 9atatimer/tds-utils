#!/usr/bin/env bash
# 03_ollama_down_is_a_fast_5xx.sh
# Given nothing listening on the external ollama's port, When a request
# goes through the gateway route, Then it gets an HTTP 5xx within 5 s (G5)
# that is not the deadline answer, so a caller never retries an outage.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_haproxy
    fixture_setup
    start_proxy
    local out code total
    out="$(curl -s -m 10 -o /dev/null -w '%{http_code} %{time_total}' "http://127.0.0.1:${PROXY_PORT}/v1/models")"
    code="${out%% *}"
    total="${out##* }"
    [[ "${code}" == 5?? ]] || fail "ollama down must be a 5xx, got ${code}"
    [[ "${code}" != "507" ]] || fail "ollama down must not be the retryable deadline answer"
    awk -v t="${total}" 'BEGIN { exit !(t < 5) }' || fail "answered after ${total}s; G5 wants under 5 s"
}

main "$@"
