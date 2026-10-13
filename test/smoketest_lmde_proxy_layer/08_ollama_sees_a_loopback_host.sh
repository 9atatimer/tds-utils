#!/usr/bin/env bash
# 08_ollama_sees_a_loopback_host.sh
# Given a request that arrives through the tunnel with the public Host
# header, When the gateway route forwards it, Then ollama sees a loopback
# Host (127.0.0.1:<ollama-port>), because ollama answers 403 to any other
# Host (tds-utils Issue#444), and the caller still gets the route header.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_haproxy
    fixture_setup
    start_upstream record
    start_proxy
    local out
    out="$(curl -s -m 10 -i -H 'Host: gateway.example.invalid' "http://127.0.0.1:${PROXY_PORT}/v1/models")"
    assert_contains "${out}" "HTTP/1.1 200" "the upstream's answer reaches the caller"
    assert_contains "$(printf '%s' "${out}" | tr 'A-Z' 'a-z')" "x-lmde-route: ollama-gateway" "route header"
    wait_for "the upstream record" test -s "${RECORD}"
    local host
    host="$(tr -d '\r' < "${RECORD}" | grep -i '^host:' | head -1)"
    assert_eq "$(printf '%s' "${host}" | tr 'A-Z' 'a-z')" "host: 127.0.0.1:${UPSTREAM_PORT}" "ollama sees a loopback Host"
}

main "$@"
