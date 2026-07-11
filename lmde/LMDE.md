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

## Artifact Acquisition (`lmde acquire`)

Distinct from the Adopted platform components above (kind, NATS, Caddy,
dnsmasq, the observability stack), which are laptop-only, `lmde` carries a
**cloud-portable artifact-acquisition capability**. It is the subset of `lmde`
a cloud sandbox can and should run; the platform components stay put.

`lmde acquire` installs the agent fleet's two packages from GitHub Packages
(`npm.pkg.github.com`):

- `@nine-at-a-time-media/clai@latest` -- the CLI AI launcher / collator.
- `@nine-at-a-time-media/ast-mcp@latest` -- the AST MCP server, landing at
  `~/.local/bin/ast-mcp`.

It owns transport, version pins, and supply-chain integrity for the fleet, and
is agent-agnostic. `--pins <file>` overrides `latest`; with no `--pins` both
packages float to `latest`. npm **registry integrity is always on**. Auth is a
classic `read:packages` PAT in `GH_AI_TOOLS_PAT`. Acquisition never runs a
piped install script -- it is a signed-package rail only.

Skills and the canonical MCP catalog are **NOT** separately acquired: they ride
inside the `@clai` package as bundled data (`clai/_data`), and `clai`
materializes them offline at configure time. Acquisition is therefore a
git-clone-free rail, which is exactly what fixes the Claude-web proxy block
(the proxy brokers only the session's own repo). `lmde acquire` does not mutate
any shell rc; if `~/.local/bin` is not on `$PATH` it warns.

See [../docs/design/LMDE-CLAI-BOUNDARY.DESIGN.md](../docs/design/LMDE-CLAI-BOUNDARY.DESIGN.md)
(authoritative for the acquire/configure boundary).

---

## Directory Structure

- `lmde/LMDE.md`: This document (the contract).
- `lmde/components/`: Installation, bootstrap, and health-check logic for specific components.
- `lmde/specs/`: Machine-readable specifications or manifests (e.g., kind cluster configs, NATS system accounts).

## Non-Goals (What LMDE is NOT)

- **Individual Tooling**: `fzf`, `jq`, `sed` are utilities, not architectural components.
- **Personal Configs**: Emacs `init.el`, `dot.bashrc`, and themes are personal preferences, not platform dependencies.
- **Project-Specific Services**: Databases or services that only one project needs.
- **`lmde acquire` as a platform component**: artifact acquisition is a
  cloud-portable *capability* of `lmde`, not an Adopted platform component; it
  installs agent-fleet packages, it is not a globally-managed service like
  kind or NATS.
- **Per-Project Browser Automation**: Chrome for Testing (used by some
  projects to give an agent driveable Chrome control without touching
  the user's main browser) is intentionally **per-project**, not LMDE.
  Each project installs its own under `~/.cache/<project>-cft/` with its
  own version, profile, and extension loadout. See
  `@nine-at-a-time-media/prompts` `SKILL.CHROME_MCP.md` for the pattern.
