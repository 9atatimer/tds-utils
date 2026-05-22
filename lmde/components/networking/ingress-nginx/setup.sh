#!/usr/bin/env bash
# setup.sh -- Install ingress-nginx (kind provider) into the current cluster.
#
# Purpose:       Deploys the ingress-nginx controller that fronts in-cluster
#                HTTP services for the LMDE *.{cluster}.localhost vhost scheme.
# Usage:         ./setup.sh
# Prerequisites: kubectl on PATH, its current context pointed at a kind
#                cluster whose node carries the label ingress-ready=true;
#                the LMDE local registry synced (see registry/sync.sh).
# Side effects:  Creates the ingress-nginx namespace and its workloads in
#                whatever cluster the current kubectl context selects.

set -euo pipefail

# --- Shared state ---

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${SCRIPT_DIR}/manifest.yaml"
NAMESPACE="ingress-nginx"
CONTROLLER_TIMEOUT="180s"

# --- Helper Functions ---

log() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] [ingress-nginx] $*"
}

require_commands() {
    local missing=0
    local cmd
    for cmd in "$@"; do
        if ! command -v "${cmd}" >/dev/null 2>&1; then
            echo "ERROR: required command not found on PATH: ${cmd}" >&2
            missing=1
        fi
    done
    [[ "${missing}" -eq 0 ]] || exit 1
}

assert_manifest_present() {
    if [[ ! -f "${MANIFEST}" ]]; then
        echo "ERROR: ingress-nginx manifest not found at ${MANIFEST}" >&2
        echo "       Re-vendor it from the kubernetes/ingress-nginx kind provider." >&2
        exit 1
    fi
}

apply_manifest() {
    log "Applying ingress-nginx manifest (${MANIFEST})..."
    kubectl apply -f "${MANIFEST}"
}

wait_for_controller() {
    log "Waiting up to ${CONTROLLER_TIMEOUT} for the controller rollout..."
    if ! kubectl rollout status deployment/ingress-nginx-controller \
        --namespace "${NAMESPACE}" --timeout="${CONTROLLER_TIMEOUT}"; then
        echo "ERROR: ingress-nginx controller did not become ready." >&2
        echo "       Inspect: kubectl -n ${NAMESPACE} get pods" >&2
        exit 1
    fi
}

# --- Main Orchestrator ---

main() {
    require_commands kubectl
    assert_manifest_present
    apply_manifest
    wait_for_controller
    log "ingress-nginx controller is ready."
}

# --- Execution Guard ---

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
