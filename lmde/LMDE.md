# LMDE: Local Managed Developer Environment

The LMDE is the set of **architectural components** and services that are globally installed and managed on this machine. These components form a stable platform contract that other projects can assume is present and available.

## The Contract

Any project running within this environment can assume the existence and availability of the following "Adopted" components.

### Core Networking & Entry

- **Caddy**: The local reverse proxy and TLS terminator.
- **dnsmasq**: Local DNS orchestration for `.localhost` and internal service discovery.

### Core Infrastructure

- **1Password CLI (`op`)**: Used for secret management and identity.
- **GPG**: For commit signing and encryption.
- **NATS**: The message bus for inter-service communication (assumed on `localhost:4222`).
- **Local Container Registry**: A local mirror (on `localhost:5001`) of vetted, pinned images to ensure supply-chain resistance and offline availability.

### Management & Automation

- **gadmin**: The administrative toolkit for GitHub, issues, and environment management.

### AI Stack

- **Ollama**: Local LLM inference server.
- **remollama**: Remote Ollama orchestration and proxying.

### Development Platforms

- **kind**: Kubernetes in Docker for local cluster orchestration.

### Observability (The Stack)

- **Prometheus**: Metrics storage and querying.
- **Grafana**: Visualization and dashboards.
- **OpenTelemetry (OTel) Collector**: The unified entry point for traces and metrics (assumed on `localhost:4317` (gRPC) or `4318` (HTTP)).

---

## Residency: in-kind vs. on the host

Not every Adopted component lives inside kind. The rule:

- **Components reachable by kind-sandboxed coding agents must run inside (or be exposed into) the kind cluster.** Mac-local agents can hit either side; sandboxed agents only see what the cluster surfaces, so anything they consume needs an in-cluster path.
- Components that only serve the host edge or *feed* kind itself (Caddy, dnsmasq, the local registry) can stay outside.
- When a component's audience widens to include sandboxed agents, plan its move into the cluster.

---

## Directory Structure

- `lmde/LMDE.md`: This document (the contract).
- `lmde/components/`: Installation, bootstrap, and health-check logic for specific components.
- `lmde/specs/`: Machine-readable specifications or manifests (e.g., kind cluster configs, NATS system accounts).

## Non-Goals (What LMDE is NOT)

- **Individual Tooling**: `fzf`, `jq`, `sed` are utilities, not architectural components.
- **Personal Configs**: Emacs `init.el`, `dot.bashrc`, and themes are personal preferences, not platform dependencies.
- **Project-Specific Services**: Databases or services that only one project needs.
- **Per-Project Browser Automation**: Chrome for Testing (used by some
  projects to give an agent driveable Chrome control without touching
  the user's main browser) is intentionally **per-project**, not LMDE.
  Each project installs its own under `~/.cache/<project>-cft/` with its
  own version, profile, and extension loadout. See
  `@nine-at-a-time-media/prompts` `SKILL.CHROME_MCP.md` for the pattern.
