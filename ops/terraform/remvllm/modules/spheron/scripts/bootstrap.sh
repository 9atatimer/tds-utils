#!/usr/bin/env bash
# bootstrap.sh — cloud-init for a Spheron GPU node (templated by terraform).
#
# Installs podman + nvidia-container-toolkit, then runs the remvllm appliance
# with GPU passthrough. Templated variables: container_image, ssh_public_key.
set -euo pipefail

CONTAINER_IMAGE="${container_image}"
SSH_PUBLIC_KEY="${ssh_public_key}"

install_runtime() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y podman curl gnupg ca-certificates

    # nvidia-container-toolkit for GPU passthrough into podman.
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -y
    apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=podman || true
}

run_appliance() {
    podman pull "$${CONTAINER_IMAGE}"
    podman run -d --name remvllm \
        --device nvidia.com/gpu=all \
        --security-opt=label=disable \
        -e SSH_PUBLIC_KEY="$${SSH_PUBLIC_KEY}" \
        -p 22:22 \
        "$${CONTAINER_IMAGE}"
}

main() {
    install_runtime
    run_appliance
}

main "$@"
