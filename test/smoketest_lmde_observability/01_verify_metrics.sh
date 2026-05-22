#!/usr/bin/env bash
# 01_verify_metrics.sh -- Smoke test for the LMDE Observability stack.

set -euo pipefail

NAMESPACE="observability"
OTEL_ENDPOINT="http://localhost:4318/v1/metrics"
METRIC_NAME="smoke_test_metric"
METRIC_VALUE=$((100 + RANDOM % 900))

log() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] $*"
}

send_metric() {
    # Use Python for portable epoch nanoseconds
    local timestamp
    timestamp=$(python3 -c 'import time; print(int(time.time() * 1000000000))')
    
    log "Sending metric ${METRIC_NAME}=${METRIC_VALUE} to ${OTEL_ENDPOINT}..."
    
    # OTLP HTTP JSON payload
    curl -sf -X POST "${OTEL_ENDPOINT}" \
        -H "Content-Type: application/json" \
        -d "{
          \"resourceMetrics\": [
            {
              \"resource\": {
                \"attributes\": [
                  { \"key\": \"service.name\", \"value\": { \"stringValue\": \"smoke-test\" } }
                ]
              },
              \"scopeMetrics\": [
                {
                  \"scope\": { \"name\": \"smoke-test-scope\" },
                  \"metrics\": [
                    {
                      \"name\": \"${METRIC_NAME}\",
                      \"gauge\": {
                        \"dataPoints\": [
                          { \"asInt\": \"${METRIC_VALUE}\", \"timeUnixNano\": \"${timestamp}\" }
                        ]
                      }
                    }
                  ]
                }
              ]
            }
          ]
        }"
}

verify_metric() {
    log "Verifying metric in Prometheus..."
    local prom_pod
    prom_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=prometheus,app.kubernetes.io/instance=prometheus" -o jsonpath="{.items[0].metadata.name}")
    
    # Start port-forward in background
    kubectl port-forward -n "${NAMESPACE}" "${prom_pod}" 9090:9090 > /dev/null 2>&1 &
    local pf_pid=$!
    
    # Resilient cleanup on exit
    trap "kill ${pf_pid} 2>/dev/null || true" EXIT
    
    # Wait for port-forward
    sleep 2
    
    # Query Prometheus
    local result
    for i in {1..30}; do
        log "Querying Prometheus (attempt ${i}/30)..."
        # Allow curl to fail and capture the output
        result=$(curl -sf "http://localhost:9090/api/v1/query?query=${METRIC_NAME}" 2>/dev/null | jq -r '.data.result[0].value[1] // empty' || echo "")
        if [[ "${result}" == "${METRIC_VALUE}" ]]; then
            log "SUCCESS: Found metric ${METRIC_NAME} with value ${METRIC_VALUE}"
            return 0
        fi
        sleep 5
    done
    
    log "FAILURE: Metric ${METRIC_NAME} not found in Prometheus or value mismatch."
    return 1
}

main() {
    send_metric
    verify_metric
}

main "$@"
