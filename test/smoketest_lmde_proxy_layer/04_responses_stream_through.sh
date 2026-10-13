#!/usr/bin/env bash
# 04_responses_stream_through.sh
# Given an upstream that answers at once, When a request goes through the
# gateway route, Then the caller gets the upstream's status and body
# unmodified (streamed, chunked) plus the route's X-LMDE-Route header.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_haproxy
    fixture_setup
    start_upstream stream
    start_proxy
    local out
    out="$(curl -s -m 10 -i "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions" --data '{}')"
    assert_contains "${out}" "HTTP/1.1 200" "upstream status passes through"
    assert_contains "$(printf '%s' "${out}" | tr 'A-Z' 'a-z')" "x-lmde-route: ollama-gateway" "route header"
    assert_contains "${out}" "first" "first chunk"
    assert_contains "${out}" "second" "second chunk"
}

main "$@"
