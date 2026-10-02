#!/usr/bin/env bash
# 03_verify_logs_traces.sh -- Smoke test for the LMDE log and trace backends.
#
# Sends one OTLP log record and one span to the collector on the host, then
# finds the log in Loki and the trace in Tempo:
#   OTLP/HTTP :4318 -> otel-collector -> Loki (logs) and Tempo (traces).
#
# Skips gracefully (exit 0) when the stack is not deployed -- a smoke test
# reports on a running system, it does not stand one up.

set -euo pipefail

CLUSTER_NAME="lmde-observability"
NAMESPACE="observability"
OTLP_BASE="http://localhost:4318"
LOKI_LOCAL_PORT="13100"
TEMPO_LOCAL_PORT="13200"
SERVICE_NAME="smoke-test-logs-traces"

PF_PIDS=()

log() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] $*"
}

skip() {
    log "SKIP: $*"
    exit 0
}

cleanup() {
    local pid
    for pid in "${PF_PIDS[@]}"; do
        kill "${pid}" 2>/dev/null || true
    done
}

# --- Action functions ---

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
}

now_nanos() {
    python3 -c 'import time; print(int(time.time() * 1000000000))'
}

port_forward() {
    local service="$1" local_port="$2" remote_port="$3"
    kubectl port-forward -n "${NAMESPACE}" "svc/${service}" \
        "${local_port}:${remote_port}" >/dev/null 2>&1 &
    PF_PIDS+=("$!")
}

send_log() {
    local ts="$1" marker="$2"
    log "Sending log record '${marker}' to ${OTLP_BASE}/v1/logs..."
    curl -sf -X POST "${OTLP_BASE}/v1/logs" \
        -H "Content-Type: application/json" \
        -d "{\"resourceLogs\":[{\"resource\":{\"attributes\":[
              {\"key\":\"service.name\",\"value\":{\"stringValue\":\"${SERVICE_NAME}\"}}]},
            \"scopeLogs\":[{\"scope\":{\"name\":\"smoke\"},\"logRecords\":[
              {\"timeUnixNano\":\"${ts}\",\"severityText\":\"INFO\",
               \"body\":{\"stringValue\":\"${marker}\"}}]}]}]}" >/dev/null
}

send_span() {
    local ts="$1" trace_id="$2" span_id="$3"
    log "Sending span (trace ${trace_id}) to ${OTLP_BASE}/v1/traces..."
    curl -sf -X POST "${OTLP_BASE}/v1/traces" \
        -H "Content-Type: application/json" \
        -d "{\"resourceSpans\":[{\"resource\":{\"attributes\":[
              {\"key\":\"service.name\",\"value\":{\"stringValue\":\"${SERVICE_NAME}\"}}]},
            \"scopeSpans\":[{\"scope\":{\"name\":\"smoke\"},\"spans\":[
              {\"traceId\":\"${trace_id}\",\"spanId\":\"${span_id}\",\"name\":\"smoke-span\",
               \"kind\":1,\"startTimeUnixNano\":\"${ts}\",
               \"endTimeUnixNano\":\"$((ts + 1000000))\"}]}]}]}" >/dev/null
}

loki_has_marker() {
    local since="$1" marker="$2"
    curl -sf -G "http://localhost:${LOKI_LOCAL_PORT}/loki/api/v1/query_range" \
        --data-urlencode "query={service_name=\"${SERVICE_NAME}\"} |= \"${marker}\"" \
        --data-urlencode "start=${since}" 2>/dev/null \
        | jq -e '.data.result | length > 0' >/dev/null 2>&1
}

tempo_has_trace() {
    local trace_id="$1"
    curl -sf "http://localhost:${TEMPO_LOCAL_PORT}/api/v2/traces/${trace_id}" 2>/dev/null \
        | jq -e '.trace.resourceSpans | length > 0' >/dev/null 2>&1
}

# --- Flow functions ---

wait_for() {
    local what="$1"
    shift
    local attempt
    for attempt in {1..24}; do
        if "$@"; then
            log "SUCCESS: ${what}"
            return 0
        fi
        log "  ${what}: not yet (attempt ${attempt}/24)..."
        sleep 5
    done
    log "FAILURE: ${what} never arrived."
    log "  Inspect: kubectl -n ${NAMESPACE} logs deploy/otel-collector"
    return 1
}

run_smoke() {
    local ts trace_id span_id marker since
    ts=$(now_nanos)
    since=$((ts - 60000000000))
    trace_id=$(openssl rand -hex 16)
    span_id=$(openssl rand -hex 8)
    marker="smoke-log-${trace_id}"

    port_forward loki "${LOKI_LOCAL_PORT}" 3100
    port_forward tempo "${TEMPO_LOCAL_PORT}" 3200
    sleep 2

    send_log "${ts}" "${marker}"
    send_span "${ts}" "${trace_id}" "${span_id}"

    local rc=0
    wait_for "log record in Loki" loki_has_marker "${since}" "${marker}" || rc=1
    wait_for "trace ${trace_id} in Tempo" tempo_has_trace "${trace_id}" || rc=1
    return "${rc}"
}

# --- Main ---

main() {
    require_commands curl jq kind kubectl openssl python3
    assert_stack_deployed
    trap cleanup EXIT INT TERM HUP
    run_smoke
}

main "$@"
