#!/usr/bin/env bash
# setup.sh -- Orchestrates the LMDE Observability stack deployment on kind.

set -euo pipefail

# --- Constants ---
CLUSTER_NAME="lmde-observability"
NAMESPACE="observability"
DATA_DIR="${HOME}/.local/share/tds-utils/observability/data"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY_NAME="kind-registry"

# Shared Networking
NET_LIB="${SCRIPT_DIR}/../networking/lib.sh"

if [[ -f "${NET_LIB}" ]]; then
    # shellcheck disable=SC1090
    source "${NET_LIB}"
fi

# Ingress (see lmde/components/networking/)
INGRESS_SETUP="${SCRIPT_DIR}/../networking/ingress-nginx/setup.sh"
CLUSTER_ALIAS="lmde"
INGRESS_PORT="32100"

# Chart Versions
PROMETHEUS_CHART_VERSION="27.5.0"
GRAFANA_CHART_VERSION="8.10.1"

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
}

ensure_kind_cluster() {
    if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
        log "Cluster ${CLUSTER_NAME} already exists."
    else
        log "Creating kind cluster ${CLUSTER_NAME}..."
        # Template the config to replace DATA_DIR
        local config_tmp
        config_tmp=$(mktemp)
        sed "s|@DATA_DIR@|${DATA_DIR}|g" "${SCRIPT_DIR}/kind-config.yaml.tpl" > "${config_tmp}"
        
        kind create cluster --name "${CLUSTER_NAME}" --config "${config_tmp}"
        rm "${config_tmp}"
    fi

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

    # Ensure registry is on the kind network
    if docker network inspect kind >/dev/null 2>&1; then
        log "Ensuring registry ${REGISTRY_NAME} is connected to kind network..."
        docker network connect kind "${REGISTRY_NAME}" || true
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

    log "Applying Prometheus Persistence (PV/PVC)..."
    kubectl apply -f "${SCRIPT_DIR}/specs/prometheus/pv.yaml"

    log "Installing Prometheus (Hardened) v${PROMETHEUS_CHART_VERSION}..."
    helm upgrade --install prometheus prometheus-community/prometheus \
        --version "${PROMETHEUS_CHART_VERSION}" \
        --namespace "${NAMESPACE}" \
        -f "${SCRIPT_DIR}/specs/prometheus/values.yaml"

    log "Ensuring Grafana Secret exists..."
    if ! kubectl get secret -n "${NAMESPACE}" grafana-admin-creds >/dev/null 2>&1; then
        local pass
        pass=$(openssl rand -base64 12)
        kubectl create secret generic grafana-admin-creds \
            --namespace "${NAMESPACE}" \
            --from-literal=admin-user="admin" \
            --from-literal=admin-password="${pass}"
        log "CREATED Grafana admin password in secret 'grafana-admin-creds'"
    fi

    log "Installing Grafana (Hardened) v${GRAFANA_CHART_VERSION}..."
    helm upgrade --install grafana grafana/grafana \
        --version "${GRAFANA_CHART_VERSION}" \
        --namespace "${NAMESPACE}" \
        --set admin.existingSecret="grafana-admin-creds" \
        --set admin.userKey="admin-user" \
        --set admin.passwordKey="admin-password" \
        -f "${SCRIPT_DIR}/specs/grafana/values.yaml"
}

deploy_otel_collector() {
    log "Deploying OTel Collector (Hardened)..."
    kubectl apply -f "${SCRIPT_DIR}/specs/otel-collector/config.yaml"
    kubectl apply -f "${SCRIPT_DIR}/specs/otel-collector/deployment.yaml"
}

deploy_dashboards() {
    log "Deploying Grafana Dashboards..."
    local dashboard_dir="${SCRIPT_DIR}/specs/grafana/dashboards"
    if [[ -d "${dashboard_dir}" ]]; then
        find "${dashboard_dir}" -name "*.yaml" -exec kubectl apply -f {} \;
    fi
}

install_ingress_controller() {
    if [[ ! -f "${INGRESS_SETUP}" ]]; then
        log "ERROR: ingress-nginx setup script not found at ${INGRESS_SETUP}"
        exit 1
    fi
    log "Installing ingress-nginx controller..."
    bash "${INGRESS_SETUP}"
}

deploy_ingress_routes() {
    log "Applying Grafana ingress route..."
    kubectl apply -f "${SCRIPT_DIR}/specs/grafana/ingress.yaml"

    if command -v register_cluster_vhost >/dev/null 2>&1; then
        register_cluster_vhost "${CLUSTER_ALIAS}" "${INGRESS_PORT}" \
            || log "WARNING: vhost registration did not complete; check Caddy."
    else
        log "WARNING: networking lib not sourced; skipping vhost registration."
    fi
}

# --- Main ---

main() {
    ensure_directories
    ensure_registry
    ensure_kind_cluster
    install_ingress_controller
    setup_namespaces
    install_helm_charts
    deploy_otel_collector
    deploy_dashboards
    deploy_ingress_routes

    log "Observability stack bootstrap complete."
}

main "$@"
