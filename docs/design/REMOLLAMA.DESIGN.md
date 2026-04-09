```markdown
# remollama — Remote Ollama Orchestrator

> **Status:** Design / Pre-Implementation
> **Created:** 2026-04-09
> **Location:** `ops/terraform/remollama/`
> **Entry Point:** `bin/remollama`

---

## What This Is

`remollama` is a CLI tool that provisions on-demand GPU instances in the cloud,
runs Ollama on them, and exposes the Ollama API locally via SSH tunnel. It
mimics the Ollama CLI experience but targets remote hardware.

**Design principles:**

- Cloud-provider agnostic (Spheron first, others later)
- Podman as the universal runtime abstraction
- Ollama-native: we enhance Ollama, we don't replace it
- Belt-and-suspenders on spend control (client + server TTL enforcement)
- Secrets from 1Password CLI (`op`), never on disk

---

## Architecture

### Layer Diagram

```
┌──────────────────────────────────────────────────────┐
│  CLI Layer                          bin/remollama     │
│  Parse args, load config, dispatch to orchestration   │
├──────────────────────────────────────────────────────┤
│  Orchestration Layer                lib/              │
│  Lifecycle, state, TTL, Modelfile sync, SSH tunnels   │
├──────────────────────────────────────────────────────┤
│  Provisioning Layer                 modules/<provider>│
│  Terraform modules — one per cloud provider           │
│  Contract: "get me to podman with GPU access"         │
├──────────────────────────────────────────────────────┤
│  Runtime Layer                      container/        │
│  The remollama appliance container                    │
│  ollama + sshd + watchdog — identical everywhere      │
└──────────────────────────────────────────────────────┘
```

### The Podman Abstraction

Every provider module's job reduces to one thing: **get me a machine that can
run podman with GPU passthrough.** The remollama appliance container is always
the same image regardless of where it runs.

This means:

- **VM-based providers** (Spheron, AWS, GCP): cloud-init installs podman +
  nvidia-container-toolkit, then `podman run` the appliance
- **Container-native providers** (future k8s-based GPU clouds): deploy the
  container image directly, skip the VM layer entirely

The provisioning module interface is always:

| Direction | Field | Description |
|-----------|-------|-------------|
| **In** | `container_image` | Registry path to the appliance image |
| **In** | `gpu_type` | GPU tier (e.g., `h100`, `a100`) |
| **In** | `ssh_public_key` | Public key for tunnel access |
| **In** | `env_vars` | Map of environment variables |
| **Out** | `host` | Instance IP or hostname |
| **Out** | `port` | SSH port on the instance |
| **Out** | `instance_id` | Provider-specific instance identifier |

What varies is whether the provider needs to stand up a VM first or can run the
container natively. That is the module's internal concern.

---

## Directory Layout

```
ops/
  terraform/
    remollama/
      container/
        Containerfile        # The appliance: ollama + sshd + watchdog
        entrypoint.sh        # PID 1: start sshd, ollama, watchdog
        watchdog.sh          # Server-side idle → self-destruct
      modules/
        spheron/             # Spheron provider module
          main.tf
          variables.tf
          outputs.tf
          scripts/
            bootstrap.sh     # cloud-init: install podman, nvidia-toolkit, run container
      modelfiles/            # Ollama Modelfiles by alias (checked in)
        example/Modelfile
      lib/                   # Bash function libraries
        orchestrate.sh       # Lifecycle: provision, connect, teardown
        state.sh             # State read/write (JSON, per-hostname)
        tunnel.sh            # SSH tunnel management
        sync.sh              # Modelfile diffing & push to remote
        secrets.sh           # 1Password `op` wrappers
        watchdog.sh          # Client-side TTL enforcement
      state/                 # .gitignored — per-hostname runtime state
      remollama.conf         # Checked-in defaults
bin/
  remollama                  # Entry point script
```

---

## Configuration

### Layered Config (later overrides earlier)

1. `ops/terraform/remollama/remollama.conf` — checked in, defaults
2. `ops/terraform/remollama/remollama.local.conf` — gitignored, machine-specific
3. Environment variables — highest priority

### Config File Format

```bash
# --- Tunables ---
REMOLLAMA_TTL_MINUTES=15          # Default TTL for an invocation
REMOLLAMA_GRACE_MINUTES=5         # Courtesy window after command completes
REMOLLAMA_WATCHDOG_TIMEOUT=600    # Server-side: seconds with no SSH → self-destruct
REMOLLAMA_PROVIDER=spheron        # Which TF module to use
REMOLLAMA_GPU_TYPE=h100           # Default GPU tier
REMOLLAMA_REGION=any              # Provider region
REMOLLAMA_STATE_DIR=""            # Override state dir (default: ops/terraform/remollama/state)

# --- Per-provider 1Password paths (override in .local.conf) ---
REMOLLAMA_SPHERON_OP_TOKEN="op://Private/Spheron/credential"
REMOLLAMA_SPHERON_OP_SSH_KEY="op://Private/spheron-ssh/private_key"
REMOLLAMA_SPHERON_OP_SSH_PUBKEY="op://Private/spheron-ssh/public_key"
# Future providers follow the pattern:
# REMOLLAMA_<PROVIDER>_OP_TOKEN="op://..."
# REMOLLAMA_<PROVIDER>_OP_SSH_KEY="op://..."
```

### Secrets Resolution

`lib/secrets.sh` resolves the right `op://` path based on the active provider:

```bash
get_provider_token() {
    local var="REMOLLAMA_${REMOLLAMA_PROVIDER^^}_OP_TOKEN"
    op read "${!var}" --no-newline
}

get_provider_ssh_key() {
    local var="REMOLLAMA_${REMOLLAMA_PROVIDER^^}_OP_SSH_KEY"
    op read "${!var}" --no-newline
}
```

---

## User Flow

### First Run (cold start)

```bash
$ remollama run codellama --ttl 15

# 1. Load config (remollama.conf → .local.conf → ENV)
# 2. Check state/<hostname>/state.json — no running instance
# 3. Resolve secrets from 1Password via `op`
# 4. terraform init + apply (Spheron module)
#    → Provisions GPU VM
#    → cloud-init: install podman + nvidia-toolkit
#    → podman run the remollama appliance container
# 5. Wait for instance ready (poll SSH, then Ollama API health)
# 6. Sync Modelfile: scp modelfiles/codellama/Modelfile → remote
#    → remote: ollama create codellama -f /tmp/Modelfile
# 7. Establish SSH tunnel: localhost:11434 → remote:11434
# 8. Write state.json (instance_id, host, port, ttl_expiry, modelfile_hash)
# 9. Print "ready — Ollama API available at localhost:11434"
# 10. Client-side TTL watchdog runs in background
```

### Reconnect (warm — instance still alive)

```bash
$ remollama run codellama --ttl 15

# 1. Load config
# 2. Check state/<hostname>/state.json — instance exists
# 3. Verify instance still alive (SSH probe)
# 4. Extend TTL (update state.json expiry)
# 5. Diff Modelfile hash — if changed, re-sync + `ollama create`
# 6. Establish SSH tunnel
# 7. Print "reconnected — Ollama API available at localhost:11434"
# Near-instant.
```

### Explicit Teardown

```bash
$ remollama stop          # Kill tunnel, leave instance running (TTL will expire)
$ remollama destroy       # terraform destroy — immediate termination
$ remollama status        # Show instance state, TTL remaining, model loaded
```

---

## State Management

### Location

```
ops/terraform/remollama/state/<hostname>/
  state.json              # Orchestration state (instance metadata, TTL, hashes)
  terraform.tfstate       # Terraform state
  terraform.tfstate.backup
```

The entire `state/` directory is `.gitignore`d. Each machine gets its own
partition, so two machines can independently manage their own remote instances.

### state.json Schema

```json
{
  "instance_id": "spheron-abc123",
  "provider": "spheron",
  "host": "203.0.113.42",
  "ssh_port": 22,
  "gpu_type": "h100",
  "model_alias": "codellama",
  "modelfile_hash": "sha256:abcdef1234...",
  "created_at": "2026-04-09T14:30:00Z",
  "ttl_expires_at": "2026-04-09T14:45:00Z",
  "tunnel_pid": null,
  "status": "running"
}
```

---

## The Remollama Appliance Container

### Containerfile

Based on the official Ollama image with GPU support. Adds:

- **sshd** — for tunnel access (authorized_keys injected via environment)
- **watchdog** — server-side idle monitor
- **entrypoint** — PID 1 supervisor for all three services

### Services

| Service | Purpose |
|---------|---------|
| `ollama serve` | The Ollama API server (port 11434) |
| `sshd` | SSH daemon for tunnel access (port 22) |
| `watchdog` | Monitors for active SSH sessions; self-destructs after idle timeout |

### Watchdog (Server-Side)

The watchdog runs as a loop inside the container:

1. Every 30 seconds, check for active SSH connections
2. If connections exist, reset the idle timer
3. If no connections for `WATCHDOG_TIMEOUT` seconds (default 600):
   - Log the event
   - Call the provider API to self-terminate the instance
   - As a fallback, `shutdown -h now`

This is the **belt** — the instance kills itself if abandoned.

### Watchdog (Client-Side)

The client-side watchdog is the **suspenders**:

1. Runs as a background process on the local machine
2. Checks `state.json` TTL expiry periodically
3. Before destroying: checks if the Ollama API is actively serving a request
4. If idle and TTL expired: `terraform destroy`
5. If active: extend grace period by `REMOLLAMA_GRACE_MINUTES`

---

## Modelfile Sync

Modelfiles live in `ops/terraform/remollama/modelfiles/<alias>/Modelfile` and
are checked into the repo. This is intentional — the model configuration is
part of the project, not ephemeral state.

### Sync Flow

1. Hash the local Modelfile: `sha256sum modelfiles/<alias>/Modelfile`
2. Compare to `modelfile_hash` in `state.json`
3. If different (or first run):
   - `scp` the Modelfile to the remote instance
   - `ssh remote "ollama create <alias> -f /tmp/Modelfile"`
   - Update hash in `state.json`
4. If unchanged: skip (model already loaded)

### Example Modelfile

```
# modelfiles/codellama/Modelfile
FROM codellama:70b
SYSTEM "You are a code assistant."
PARAMETER temperature 0.3
PARAMETER num_ctx 8192
```

---

## Terraform Modules

### Module Interface Contract

Every provider module must accept these variables and produce these outputs.
This is the provider-agnostic contract.

#### Required Variables

| Variable | Type | Description |
|----------|------|-------------|
| `container_image` | `string` | Container image to deploy |
| `gpu_type` | `string` | GPU tier (`h100`, `a100`) |
| `ssh_public_key` | `string` | SSH public key for access |
| `provider_token` | `string` | Provider API credential |
| `instance_name` | `string` | Name tag for the instance |
| `env_vars` | `map(string)` | Environment variables for the container |

#### Required Outputs

| Output | Type | Description |
|--------|------|-------------|
| `host` | `string` | Instance IP or hostname |
| `ssh_port` | `number` | SSH port |
| `instance_id` | `string` | Provider-specific instance ID |

### Spheron Module (Initial Provider)

Uses the `spheronFdn/spheron` Terraform provider (v1.0.0+).

- Resource: `spheron_instance`
- Deploys a GPU VM with cloud-init bootstrap
- Bootstrap script: install podman + nvidia-container-toolkit, pull and run
  the appliance container
- GPU options: H100 (~$2.50/hr on-demand), A100 (~$1.14/hr on-demand)
- Networking: all ports open by default, SSH on port 22

---

## Security Model

### Current (MVP)

- **Transport:** SSH tunnel from localhost to remote Ollama API. No ports
  exposed to the internet beyond SSH.
- **Authentication:** SSH key-based auth. Keys live in 1Password, retrieved
  at runtime via `op`.
- **Secrets:** Never written to disk. Provider tokens and SSH keys are piped
  from `op` directly into terraform and ssh commands via process substitution
  or environment variables.
- **Network exposure:** Only SSH (port 22) needs to be reachable. The Ollama
  API (11434) is bound to localhost on the remote and tunneled.

### Future Considerations

- WireGuard or Tailscale as an alternative to SSH tunneling
- mTLS for direct API exposure (if SSH tunneling becomes a bottleneck)
- IAM-style access controls for multi-user scenarios

---

## Container Registry

For the MVP, two options (decision deferred):

1. **GitHub Container Registry (ghcr.io)** — the repo is already on GitHub,
   free for public images. Provider modules pull from the registry.
2. **Direct transfer** — `podman save | ssh | podman load`. No registry
   dependency, but slower on cold start.

GHCR is the likely choice. The `Containerfile` builds locally; CI or a manual
`podman push` publishes to `ghcr.io/9atatimer/remollama-appliance`.

---

## Spend Controls

### Defense in Depth

| Layer | Mechanism | Trigger |
|-------|-----------|---------|
| Client TTL | Background watchdog process | TTL expires + no active requests |
| Server watchdog | In-container idle monitor | No SSH connections for N seconds |
| Grace period | TTL extension on activity | Active Ollama request at TTL expiry |
| Manual kill | `remollama destroy` | User choice |

### Failure Modes

| Scenario | What happens |
|----------|-------------|
| User kills remollama, walks away | Client TTL watchdog dies. Server watchdog sees no SSH → self-destructs after `WATCHDOG_TIMEOUT`. |
| Network partition | Server watchdog sees no SSH → self-destructs. Client sees SSH probe fail → marks instance dead in state. |
| Laptop sleeps, wakes up later | Client TTL may have expired. `remollama run` reconnects if instance alive, provisions new if dead. |
| Both watchdogs fail somehow | Spheron billing runs. This is the residual risk. Mitigate with provider-level budget alerts. |

---

## CLI Interface

```
remollama — Remote Ollama orchestrator

Usage:
  remollama run <alias> [--ttl <minutes>] [--gpu <type>] [--provider <name>]
  remollama stop
  remollama destroy
  remollama status
  remollama list-models

Commands:
  run          Provision (or reconnect to) a remote instance and open tunnel
  stop         Close the SSH tunnel; instance stays alive until TTL expires
  destroy      Tear down the remote instance immediately (terraform destroy)
  status       Show instance state, TTL remaining, model loaded
  list-models  List available model aliases (from modelfiles/)

Options:
  --ttl <min>       TTL in minutes (default: $REMOLLAMA_TTL_MINUTES)
  --gpu <type>      GPU tier: h100, a100 (default: $REMOLLAMA_GPU_TYPE)
  --provider <name> Cloud provider (default: $REMOLLAMA_PROVIDER)
  -v, --verbose     Verbose output
  -h, --help        Show this help
```

---

## Open Questions

- [ ] Container registry choice: GHCR vs direct transfer vs defer?
- [ ] Should the server-side watchdog call the Spheron API to self-terminate,
      or just `shutdown -h now` and rely on the provider to stop billing?
- [ ] Do we want a `remollama pull <model>` command that pre-pulls a base model
      on the remote (separate from Modelfile create)?
- [ ] Log shipping: should the remote instance ship ollama logs somewhere, or
      is SSH + `journalctl` sufficient for debugging?

---

## Future Providers

Adding a new provider requires:

1. A new Terraform module at `modules/<provider>/` implementing the contract
   (variables in, host/port/instance_id out)
2. A bootstrap script (if VM-based) that installs podman + nvidia-toolkit and
   runs the appliance container
3. `op://` paths for the provider's credentials in config
4. That's it. The orchestration layer, container, and CLI are unchanged.

---

## Dependencies

| Tool | Purpose | Install |
|------|---------|---------|
| `terraform` | Infrastructure provisioning | `brew install terraform` or tfenv |
| `op` | 1Password CLI for secrets | `brew install 1password-cli` |
| `podman` | Container builds (local dev) | `brew install podman` |
| `jq` | JSON parsing in bash | `brew install jq` |
| `ssh` | Tunnel and remote access | Pre-installed |
```

There it is — full contents.

