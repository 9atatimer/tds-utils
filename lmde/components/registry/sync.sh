#!/usr/bin/env bash
# sync.sh -- Syncs vetted, pinned images to the local container registry.

set -euo pipefail

REGISTRY_PORT="5001"
REGISTRY_NAME="kind-registry"
LOCAL_REGISTRY="localhost:${REGISTRY_PORT}"
IMAGES_FILE="$(dirname "${BASH_SOURCE[0]}")/images.txt"

log() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] $*"
}

ensure_registry() {
    if docker ps --filter "name=${REGISTRY_NAME}" --format '{{.Names}}' | grep -q "^${REGISTRY_NAME}$"; then
        log "Registry container ${REGISTRY_NAME} is already running."
    else
        log "Starting local registry container on port ${REGISTRY_PORT}..."
        docker run -d --restart=always -p "127.0.0.1:${REGISTRY_PORT}:5000" --name "${REGISTRY_NAME}" registry:2
    fi
}

sync_images() {
    log "Syncing images from ${IMAGES_FILE}..."
    while read -r line || [[ -n "$line" ]]; do
        # Skip comments and empty lines
        [[ "${line}" =~ ^#.*$ ]] && continue
        [[ -z "${line}" ]] && continue

        local upstream_full="${line}"
        # Extract image name without digest for tagging
        local image_name_tag="${upstream_full%%@*}"
        # Extract base name (e.g., grafana/grafana)
        local base_name="${image_name_tag##*/}"
        # Handle cases with multiple slashes (e.g., quay.io/prometheus/node-exporter)
        local repo_path="${image_name_tag#*./}" # strip registry
        repo_path="${image_name_tag#*/}" # strip registry or first part
        
        # Simpler approach: use the part after the first slash as the local name
        local local_tag="${LOCAL_REGISTRY}/${base_name}"
        
        log "Pulling ${upstream_full}..."
        docker pull "${upstream_full}"
        
        log "Tagging as ${local_tag}..."
        docker tag "${upstream_full}" "${local_tag}"
        
        log "Pushing to local registry..."
        docker push "${local_tag}"
    done < "${IMAGES_FILE}"
}

main() {
    ensure_registry
    sync_images
    log "Image sync complete."
}

main "$@"
