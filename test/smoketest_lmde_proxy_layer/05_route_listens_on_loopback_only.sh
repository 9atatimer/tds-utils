#!/usr/bin/env bash
# 05_route_listens_on_loopback_only.sh
# Given the layer running the gateway route, Then its only TCP listener is
# 127.0.0.1:<proxy-port> -- one loopback listener per route (Q12) -- and
# the upstream hop it holds open is a unix socket, not a second port the
# tunnel could ever be pointed at.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_haproxy
    fixture_setup
    start_proxy
    local hpid listeners
    hpid="$(lsof -nP -t -iTCP:"${PROXY_PORT}" -sTCP:LISTEN | head -1)"
    [[ -n "${hpid}" ]] || fail "no listener pid"
    listeners="$(lsof -nP -a -p "${hpid}" -iTCP -sTCP:LISTEN -Fn | sed -n 's/^n//p' | sort -u)"
    assert_eq "${listeners}" "127.0.0.1:${PROXY_PORT}" "TCP listeners of the proxy"
    [[ -S "${ROOT}/run/ollama-gateway.sock" ]] || fail "the hold hop's unix socket is missing"
}

main "$@"
