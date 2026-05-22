#!/usr/bin/env bash
# 02_verify_grafana_vhost.sh -- Smoke test for the Grafana host vhost.
#
# Verifies the host-ingress chain for the LMDE observability cluster:
#   grafana.lmde.localhost -> Caddy -> ingress-nginx -> Grafana Service.
#
# Skips gracefully (exit 0) when the stack is not deployed -- a smoke test
# reports on a running system, it does not stand one up. When the stack IS
# deployed but the vhost does not serve Grafana, the test fails.

set -euo pipefail

CLUSTER_NAME="lmde-observability"
VHOST="grafana.lmde.localhost"
INGRESS_PORT="32100"
CADDY_ADMIN_URL="http://localhost:2019"
HEALTH_URL="https://${VHOST}/api/health"

log() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] $*"
}

skip() {
    log "SKIP: $*"
    exit 0
}

require_commands() {
    local cmd
    for cmd in "$@"; do
        command -v "${cmd}" >/dev/null 2>&1 || skip "required command not found: ${cmd}"
    done
}

assert_stack_deployed() {
    if ! kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
        skip "kind cluster '${CLUSTER_NAME}' not found -- run observability/setup.sh first"
    fi
    if ! curl -sf --max-time 2 "${CADDY_ADMIN_URL}/config/" >/dev/null 2>&1; then
        skip "Caddy admin API unreachable at ${CADDY_ADMIN_URL}"
    fi
}

verify_vhost() {
    log "Requesting ${HEALTH_URL} (resolved to 127.0.0.1)..."
    local attempt body
    for attempt in {1..12}; do
        if body=$(curl -fsS -k -L --max-time 10 \
            --resolve "${VHOST}:443:127.0.0.1" "${HEALTH_URL}" 2>/dev/null) \
            && [[ "${body}" == *'"database"'* ]]; then
            log "SUCCESS: ${VHOST} serves Grafana (health: ${body})"
            return 0
        fi
        log "  not ready yet (attempt ${attempt}/12)..."
        if [[ "${attempt}" -lt 12 ]]; then
            sleep 5
        fi
    done
    log "FAILURE: ${VHOST} never served a healthy Grafana response."
    log "  Chain: Caddy(*.lmde.localhost) -> 127.0.0.1:${INGRESS_PORT} -> ingress-nginx -> grafana"
    log "  Inspect: kubectl -n observability get ingress,svc,pods"
    return 1
}

main() {
    require_commands curl kind
    assert_stack_deployed
    verify_vhost
}

main "$@"
