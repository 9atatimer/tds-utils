#!/usr/bin/env bash
# 01_deadline_answer_is_a_distinct_507.sh
# Given an upstream that sends nothing (a cold model load), When a request
# goes through the gateway route, Then its first byte leaves at the
# deadline, not later, as HTTP 507 -- the deadline answer, the one response
# a caller retries -- carrying the route's X-LMDE-Route header. 507 is none
# of the 5xx a caller can otherwise see: HAProxy's own 500/502/503/504,
# cloudflared's 502, ollama's 500/503, or Cloudflare's 52x/530.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_haproxy
    fixture_setup
    start_upstream silent 4
    start_proxy
    local headers ttfb code
    headers="$(curl -s -m 10 -D - -o /dev/null -w 'ttfb=%{time_starttransfer}\n' \
        -H 'content-type: application/json' --data '{"model":"m","messages":[]}' \
        "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions")"
    code="$(printf '%s\n' "${headers}" | awk 'NR==1 {print $2}')"
    ttfb="$(printf '%s\n' "${headers}" | sed -n 's/^ttfb=//p')"

    assert_eq "${code}" "507" "deadline answer status"
    assert_contains "$(printf '%s' "${headers}" | tr 'A-Z' 'a-z')" "x-lmde-route: ollama-gateway" "route header on the deadline answer"
    awk -v t="${ttfb}" 'BEGIN { exit !(t >= 0.9 && t < 2.5) }' \
        || fail "first byte at ${ttfb}s; want it at the 1 s deadline"
    case "${code}" in
        500|502|503|504|52[0-9]|530) fail "deadline answer collides with another 5xx: ${code}" ;;
    esac
}

main "$@"
