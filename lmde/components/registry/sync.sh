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
    # Extract pinned registry image from images.txt
    local pinned_registry
    pinned_registry=$(grep "docker.io/library/registry:2@" "${IMAGES_FILE}" | head -n 1)
    
    if [[ -z "${pinned_registry}" ]]; then
        log "WARNING: Pinned registry image not found in ${IMAGES_FILE}. Falling back to floating tag."
        pinned_registry="registry:2"
    fi

    if docker ps --filter "name=${REGISTRY_NAME}" --format '{{.Names}}' | grep -q "^${REGISTRY_NAME}$"; then
        log "Registry container ${REGISTRY_NAME} is already running."
    else
        log "Starting local registry container on port ${REGISTRY_PORT} using ${pinned_registry}..."
        docker run -d --restart=always -p "127.0.0.1:${REGISTRY_PORT}:5000" --name "${REGISTRY_NAME}" "${pinned_registry}"
    fi
}

sync_images() {
    log "Syncing images from ${IMAGES_FILE}..."
    while read -r line || [[ -n "$line" ]]; do
        # Skip comments and empty lines
        [[ "${line}" =~ ^#.*$ ]] && continue
        [[ -z "${line}" ]] && continue

        local upstream_full="${line}"
        # Extract image name with tag but WITHOUT digest for local tagging
        # e.g., docker.io/grafana/grafana:12.3.1@sha256:hash -> grafana/grafana:12.3.1
        local image_with_tag="${upstream_full%%@*}"
        
        # Extract the base name (including tag) to use in local registry
        # e.g., docker.io/grafana/grafana:12.3.1 -> grafana:12.3.1
        local base_name_with_tag="${image_with_tag##*/}"
        
        local local_tag="${LOCAL_REGISTRY}/${base_name_with_tag}"
        
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
