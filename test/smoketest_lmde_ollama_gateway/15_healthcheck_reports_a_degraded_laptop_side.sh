#!/usr/bin/env bash
# 15_healthcheck_reports_a_degraded_laptop_side.sh
# Given the laptop side, When the healthcheck runs, Then it is OK only when
# the external ollama answers on its port and the gateway route answers on
# the proxy port with its X-LMDE-Route header; a missing ollama, a missing
# route, a listener on the proxy port that is not the route, or a route
# that cannot list models (an error status from ollama behind it -- e.g. a
# store it cannot read) is DEGRADED and named.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_curl
    local out status

    healthy_local
    status=0; out="$(run_healthcheck)" || status=$?
    assert_eq "${status}" "0" "healthy laptop side; output: ${out}"
    assert_contains "${out}" "external-ollama: OK" "ollama line"
    assert_contains "${out}" "deadline-proxy: OK" "route line"

    rm -f "${WORK}/curl/"*11435*
    status=0; out="$(run_healthcheck)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "ollama down must be DEGRADED"
    assert_contains "${out}" "external-ollama: DEGRADED" "ollama named"

    healthy_local
    canned "http://127.0.0.1:11436/v1/models" 200 "server: something-else"
    status=0; out="$(run_healthcheck)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "a foreign listener on the proxy port must be DEGRADED"
    assert_contains "${out}" "deadline-proxy: DEGRADED" "route named"

    healthy_local
    canned "http://127.0.0.1:11436/v1/models" 500 "X-LMDE-Route: ollama-gateway"
    status=0; out="$(run_healthcheck)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "a route that cannot list models must be DEGRADED; output: ${out}"
    assert_contains "${out}" "HTTP 500" "status named"
}

main "$@"
