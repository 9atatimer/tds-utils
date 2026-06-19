# LMDE-BACKPLANE -- Unified Message Bus (NATS-in-kind)

> **Status:** DRAFT
> **Created:** 2026-06-01
> **Location:** `docs/design/LMDE-BACKPLANE.DESIGN.md`

---

## Overview

The LMDE Backplane provides a unified communication layer for all local agents and services. Currently, NATS runs as a standalone process on the host, reachable only via `localhost:4222`. This design moves the backplane into the `kind` cluster to ensure parity between host-local and sandboxed agents.

## Goals

1.  **Parity**: Ensure sandboxed agents (running in `kind`) and host agents (running in `zsh/emacs`) can reach the same NATS bus.
2.  **Stability**: Use a standard K8s deployment for NATS with persistent storage.
3.  **Discovery**: Provide a stable DNS name (`nats.lmde.localhost`) for all clients.
4.  **Security**: Transition from anonymous loopback to authenticated access.

## Architecture

### 1. The NATS Server
- **Deployment**: Single-node NATS deployment in the `kind` cluster.
- **Image**: Vetted and pinned `nats:2.10.18-alpine` (pinned by digest in manifest).
- **Storage**: Persistent storage via HostPath bind-mount from the Mac host into the `kind` node (`extraMounts` in cluster config) to ensure data survives cluster recreation.

### 2. Connectivity & Ingress

#### Host-to-Cluster (Mac-local agents)
Mac-local agents will reach NATS via **Caddy** acting as the host edge:
- **DNS**: `nats.lmde.localhost`
- **Port**: 4222
- **TLS**: Terminated by **Caddy** using local CA certs. Caddy proxies plaintext TCP to the `kind` NodePort or ingress IP.

#### Cluster-Internal (Sandboxed agents)
Agents running in `kind` pods will use the standard K8s Service:
- **DNS**: `nats.default.svc.cluster.local` (or simply `nats`)
- **Port**: 4222
- **Auth**: Plaintext (internal network is trusted; boundary is at the host edge).

### 3. Authentication Model

The backplane will move from anonymous loopback to **Token-based Authentication**.

- **Source of Truth**: 1Password (`op` CLI).
- **Secrets Management**: Tokens injected into `kind` as K8s Secrets.
- **Client Configuration**: To avoid `op` bottlenecks, the LMDE bootstrap will export `NATS_TOKEN` to a local `.env` file for host-side agents.

## Key Decisions

### [DECISION 1]: In-cluster NATS vs. Exposing Host NATS
We will run **NATS in-cluster**. 
- **Rationale**: Simplifies residency rules for sandboxed agents and unifies infrastructure lifecycle.

### [DECISION 2]: Caddy as Unified Edge
We will use **Caddy** for NATS TCP proxying rather than `ingress-nginx` snippets.
- **Rationale**: Keeps the LMDE host-edge consistent. Caddy already handles `.localhost` TLS/DNS; it should own the NATS entry point too.

### [DECISION 3]: Host Bind-Mount for Persistence
We will use `extraMounts` in the `kind` configuration to map a host directory (e.g. `~/.local/share/lmde/nats`) into the pod.
- **Rationale**: Ensures JetStream data outlives the `kind` container lifecycle, fulfilling the Stability goal.

## Open Questions

1. **Migration Path**: Is there any existing JetStream data on the host that *must* be migrated, or can we start with a clean slate? (Recommendation: clean slate for MVP).

## Rejections

- **ingress-nginx TCP Snippets**: Rejected to avoid split-brain edge architecture between Caddy and Ingress.
- **Raw HostPath**: Rejected because data is lost on cluster recreation.
