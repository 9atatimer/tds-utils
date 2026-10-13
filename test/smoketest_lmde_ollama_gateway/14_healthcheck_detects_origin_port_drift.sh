#!/usr/bin/env bash
# 14_healthcheck_detects_origin_port_drift.sh
# Q8 (a): an allow-listed request through the tunnel is verified to reach
# the deadline proxy. Given the edge and a consumer credential, When the
# healthcheck sends GET /v1/models through the edge, Then it is healthy
# only if the answer carries the route's X-LMDE-Route header (the deadline
# answer counts: it is the proxy speaking); an answer without it means the
# edge's origin port reaches some other listener -- DRIFT, DEGRADED. The
# credential travels on curl's stdin, never its argv, and is never printed.
# Without the edge configured the check is skipped, not failed.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_curl
    healthy_local
    local out status env=()
    while IFS= read -r line; do env+=("${line}"); done < <(edge_env)

    canned "${EDGE_URL}/v1/models" 200 "X-LMDE-Route: ollama-gateway"
    status=0; out="$(run_healthcheck "${env[@]}")" || status=$?
    assert_eq "${status}" "0" "healthy through the edge; output: ${out}"
    assert_contains "${out}" "edge: OK" "edge reaches the deadline proxy"

    canned "${EDGE_URL}/v1/models" 507 "X-LMDE-Route: ollama-gateway"
    status=0; out="$(run_healthcheck "${env[@]}")" || status=$?
    assert_eq "${status}" "0" "the deadline answer is still the proxy; output: ${out}"

    canned "${EDGE_URL}/v1/models" 200 "content-type: application/json"
    status=0; out="$(run_healthcheck "${env[@]}")" || status=$?
    [[ "${status}" -ne 0 ]] || fail "an origin that is not the proxy must be DEGRADED; output: ${out}"
    assert_contains "${out}" "DRIFT" "drift named"

    canned "${EDGE_URL}/v1/models" 403
    status=0; out="$(run_healthcheck "${env[@]}")" || status=$?
    [[ "${status}" -ne 0 ]] || fail "a refused credential must be DEGRADED"
    assert_contains "${out}" "403" "status named"

    assert_not_contains "$(cat "${WORK}/curl.argv")" "${FAKE_CLIENT_SECRET}" "secret never in curl argv"
    assert_contains "$(cat "${WORK}/curl.stdin")" "X-Example-Client-Secret: ${FAKE_CLIENT_SECRET}" "secret header on stdin, named by the item"
    assert_contains "$(cat "${WORK}/curl.stdin")" "X-Example-Client-Id: fake-client-id" "id header on stdin"
    assert_not_contains "${out}" "${FAKE_CLIENT_SECRET}" "secret never printed"

    status=0; out="$(run_healthcheck)" || status=$?
    assert_eq "${status}" "0" "unconfigured edge is not a failure; output: ${out}"
    assert_contains "${out}" "edge: SKIPPED" "skip is stated"

    status=0; out="$(run_healthcheck "OLLAMA_GATEWAY_EDGE_URL=${EDGE_URL}")" || status=$?
    [[ "${status}" -ne 0 ]] || fail "an edge URL without a credential must be DEGRADED"
    assert_contains "${out}" "OLLAMA_GATEWAY_CLIENT_SECRET" "missing credential variable named"
}

main "$@"
