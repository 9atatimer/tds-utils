# LMDE Component: Local Registry

## Overview

Ensures supply-chain resistance by hosting vetted, pinned images locally. The `kind` cluster is configured to pull from this registry (`localhost:5001`) as its primary source.

## Strategy

1. **Source**: Upstream images are pulled (e.g., from `ghcr.io` or Docker Hub).
2. **Vetting**: Images are pinned by content hash (digest), not just tags.
3. **Mirroring**: A local script (`sync.sh`) pulls the pinned images, retags them for `localhost:5001`, and pushes them to the local registry.
4. **Integration**: `kind` is started with a configuration that connects it to this registry.

## Components

- **Registry**: Standard `registry:2` container running via Docker or as a pod in `kind` (Bootstrap uses a standalone container to avoid circular dependencies).
- **Sync Logic**: `sync.sh` reads `images.txt` (a list of `name@sha256:hash`) and performs the retag/push.

## Ports

- `5001`: Local registry endpoint.
