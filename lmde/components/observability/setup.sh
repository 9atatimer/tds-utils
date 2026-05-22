#!/usr/bin/env bash
# setup.sh -- Orchestrates the LMDE Observability stack deployment on kind.

set -euo pipefail

# --- Constants ---
CLUSTER_NAME="lmde-observability"
NAMESPACE="observability"
DATA_DIR="${HOME}/.local/share/tds-utils/observability/data"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY_NAME="kind-registry"

# --- Helper Functions ---

log() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] $*"
}

ensure_directories() {
    log "Ensuring data directory exists at ${DATA_DIR}..."
    mkdir -p "${DATA_DIR}"
}

ensure_registry() {
    log "Checking local registry..."
    "${SCRIPT_DIR}/../registry/sync.sh"
    
    # Ensure registry is on the kind network
    if docker network inspect kind >/dev/null 2>&1; then
        log "Connecting registry to kind network..."
        docker network connect kind "${REGISTRY_NAME}" || true
    fi
}

ensure_kind_cluster() {
    if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
        log "Cluster ${CLUSTER_NAME} already exists. To recreate, run 'kind delete cluster --name ${CLUSTER_NAME}'"
    else
        log "Creating kind cluster ${CLUSTER_NAME}..."
        kind create cluster --config "${SCRIPT_DIR}/kind-config.yaml"
        
        log "Configuring node registry mirrors..."
        local REGISTRY_DIR="/etc/containerd/certs.d/localhost:5001"
        for node in $(kind get nodes --name "${CLUSTER_NAME}"); do
            docker exec "${node}" mkdir -p "${REGISTRY_DIR}"
            docker exec -i "${node}" bash -c "cat > ${REGISTRY_DIR}/hosts.toml" <<EOF
server = "http://kind-registry:5000"

[host."http://kind-registry:5000"]
  capabilities = ["pull", "resolve"]
EOF
        done
    fi
}

setup_namespaces() {
    log "Creating namespace ${NAMESPACE}..."
    kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
}

install_helm_charts() {
    log "Adding Helm repositories..."
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update

    log "Installing Prometheus (Hardened)..."
    helm upgrade --install prometheus prometheus-community/prometheus \
        --namespace "${NAMESPACE}" \
        -f "${SCRIPT_DIR}/specs/prometheus/values.yaml"

    log "Installing Grafana (Hardened)..."
    helm upgrade --install grafana grafana/grafana \
        --namespace "${NAMESPACE}" \
        -f "${SCRIPT_DIR}/specs/grafana/values.yaml"
}

deploy_otel_collector() {
    log "Deploying OTel Collector (Hardened)..."
    kubectl apply -f "${SCRIPT_DIR}/specs/otel-collector/config.yaml"
    kubectl apply -f "${SCRIPT_DIR}/specs/otel-collector/deployment.yaml"
}

# --- Main ---

main() {
    ensure_directories
    ensure_registry
    ensure_kind_cluster
    setup_namespaces
    install_helm_charts
    deploy_otel_collector
    log "Observability stack bootstrap complete."
}

main "$@"
