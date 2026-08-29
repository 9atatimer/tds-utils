# LMDE -- Local Managed Developer Environment

> **Status:** ADOPTED (per-part status in the table below)
> **Date:** 2026-08-14
> **Authors:** Gemini CLI (observability first draft), Claude (ingress
> revision, boundary design, this consolidation), from design discussions
> with Todd
> **Supersedes:** `LMDE-OBSERVABILITY.DESIGN.md`,
> `LMDE-BACKPLANE.DESIGN.md`, `LMDE-CLAI-BOUNDARY.DESIGN.md` (all three
> deleted in the same commit that added this file)
> **Depends on:** [LMDE.md](../../lmde/LMDE.md) (the runtime contract),
> [SANDBOX-LIFECYCLE.DESIGN.md](./SANDBOX-LIFECYCLE.DESIGN.md)
> (authoritative for WHEN acquire runs)

---

## Overview

The LMDE is the set of architectural components and services that are
globally installed and managed on Todd's machine, plus one cloud-portable
capability -- `lmde acquire` -- that installs the agent fleet's artifacts on
any surface. This document is the single design record for all of it: the
platform contract and its residency rule, the acquisition rail and its
boundary with `clai`, the observability stack, the host-ingress pattern, and
the message backplane.

One tool, one design doc. Anything an implementer needs to know about why
`lmde` is shaped the way it is belongs here.

### Part status

| Part | Status | Origin |
|---|---|---|
| Platform contract + residency | ADOPTED | `lmde/LMDE.md` (contract text stays there) |
| Artifact acquisition + the lmde/clai boundary | ADOPTED (Revisions 1 and 2 folded in) | `LMDE-CLAI-BOUNDARY.DESIGN.md` |
| Observability stack | ADOPTED (deployed; ingress revision live) | `LMDE-OBSERVABILITY.DESIGN.md` |
| Host ingress pattern | ADOPTED | `LMDE-OBSERVABILITY.DESIGN.md` section 4 |
| Backplane (NATS-in-kind) | DRAFT (designed, not implemented) | `LMDE-BACKPLANE.DESIGN.md` |

### Document map

| For | Read |
|---|---|
| What a project may ASSUME is present (the contract itself) | [`lmde/LMDE.md`](../../lmde/LMDE.md) |
| Why lmde is built this way, and every decision behind it | this document |
| WHEN acquire runs in a cloud sandbox (cache seeder vs session authority) | [SANDBOX-LIFECYCLE.DESIGN.md](./SANDBOX-LIFECYCLE.DESIGN.md) |
| What `clai provision` does with what acquire installed | template-tools `packages/clai/docs/CLAI.DESIGN.md` |
| The historical unified provisioning design | [PROVISION.DESIGN.md](./PROVISION.DESIGN.md) |
| Which technologies are Adopted / Trial / Hold here | [`lmde/TECH_RADAR.md`](../../lmde/TECH_RADAR.md) |

---

## Goals

1. **Stable platform contract** -- Any project on this machine can assume
   the Adopted components exist at their documented addresses, without
   probing or vendoring its own copy.
2. **Residency parity** -- A kind-sandboxed coding agent reaches the same
   services a host-local agent does; no component is silently host-only
   once its audience includes sandboxed agents.
3. **Clean concern split on provisioning** -- Every provisioning
   responsibility lands wholly in Acquire (lmde) or Configure (clai),
   decided by one agent-agnostic / agent-aware test, with no straddlers.
4. **Loose coupling across that split** -- The boundary is a fixed set of
   filesystem locations, not a runtime manifest or receipt. Either side can
   be reimplemented without the other changing, as long as the paths hold.
5. **Cloud parity on acquisition** -- A fresh cloud sandbox acquires the
   same artifacts a laptop does, over a rail the Claude-web git proxy does
   not block.
6. **Data floats, executables are pinned** -- A skills merge reaches the
   next session on every surface with no human step beyond the merge;
   executable versions change only through a reviewed pin bump.
7. **Persistent, hermetic observability** -- Metrics survive kind restarts
   and cluster recreation; every image is digest-pinned and served from a
   local registry.
8. **Named host access** -- Every in-cluster UI is reachable at a stable
   `<service>.lmde.localhost` URL that survives pod restarts, rollouts, and
   cluster recreation.
9. **Fail-open everywhere** -- No acquisition or provisioning failure ever
   blocks a session from starting. Degradation is loud and names what is
   stale.

---

## Non-Goals

- **Individual tooling.** `fzf`, `jq`, `sed` are utilities, not
  architectural components.
- **Personal configs.** Emacs `init.el`, `dot.bashrc`, themes.
- **Project-specific services.** A database only one project needs.
- **`lmde acquire` as a platform component.** Acquisition is a
  cloud-portable capability of lmde, not a globally-managed service like
  kind or NATS.
- **Per-project browser automation.** Chrome for Testing is deliberately
  per-project (`~/.cache/<project>-cft/`), never LMDE.
- **Log aggregation in the observability stack.** Structured OTLP events
  are in scope; raw terminal logs stay `log-hoarder`'s.
- **Multi-node scalability.** Single-user laptop scale.
- **Public ingress.** The stack is strictly local, never routable.
- **Service mesh.** No mTLS, traffic-shaping, or east-west policy between
  components. Routing is north-south only (host -> cluster).
- **A receipt / install manifest between lmde and clai.** Explicitly
  rejected; see Rejections.
- **Cloud telemetry / launcher parity (gap G1).** clai injects the
  telemetry environment at agent launch, and in the cloud the provider
  launches the agent with no clai wrapper. Orthogonal problem.
- **Reworking lmde's platform components to serve acquisition.** kind,
  NATS, Caddy, and the observability stack are untouched by the acquire
  capability; it sits alongside them.

---

## Architecture Overview

```
+---------------------------------------------------------------------------+
| HOST LAPTOP                                                               |
|                                                                           |
|   Coding agent ----OTLP----> 127.0.0.1:4317 / :4318                       |
|   Coding agent ----NATS----> nats.lmde.localhost:4222  (planned)          |
|                                                                           |
|   Browser --grafana.lmde.localhost--> Caddy --http--> 127.0.0.1:32100     |
|     (*.localhost resolves to loopback natively ; Caddy terminates TLS)    |
+---------------------------------------------------------------------------+
        |                                              |
        | kind extraPortMappings:                      |
        |   127.0.0.1:32100      <->  node:80          |
        |   127.0.0.1:4317/4318  <->  node:4317/4318   |
        v                                              v
+---------------------------------------------------------------------------+
| KIND CLUSTER  "lmde-observability"                                        |
|                                                                           |
|   ingress-nginx --(Host: grafana.lmde.localhost)--> Grafana Service       |
|                                                          |                |
|   OTel Collector ----> Prometheus <----(PromQL)---- Grafana               |
|                       (HostPath PV)                                       |
|   NATS (planned)  <-- in-cluster clients via nats.default.svc             |
+---------------------------------------------------------------------------+

+---------------------------------------------------------------------------+
| LOCAL REGISTRY  127.0.0.1:5001  <-- sync.sh <-- Upstream / GHCR           |
| (kind nodes pull all images from here; digests pinned in images.txt)      |
+---------------------------------------------------------------------------+

  ACQUISITION RAIL (cloud-portable; independent of everything above)

        ACQUIRE (lmde)                          CONFIGURE (clai)
  agent-agnostic, owns transport           agent-aware, owns collation
+------------------------------+        +-------------------------------+
| npm from GitHub Packages:    |        | reads the convention paths    |
|   skills  (DATA, floats)     |        | collates catalog <- repo      |
|   clai / ast-mcp / gadmin /  |        |          clai.d <- user clai.d|
|   git-mirror (fleet-pinned)  |        | emits per-agent MCP dialects  |
+------------------------------+        | places skills per agent       |
              |                         | injects OTel env at launch    |
     no call, no payload                | trailing oddities epilogue    |
     only the paths below               +-------------------------------+
              v                                      ^
   ~/.local/bin/<server>                             |
   ~/.local/lib/node_modules/@nine-at-a-time-media/skills/
   clai on $PATH  --------------------------------->-+
```

---

## Design

### 1. Platform contract and residency

The Adopted component list is the contract and lives in
[`lmde/LMDE.md`](../../lmde/LMDE.md), because its audience is every project
on the machine at runtime, not a reader of design rationale. This document
does not restate the list; it records the rule that decides where a
component lives.

**The residency rule.** Not every Adopted component belongs inside kind:

- A component reachable by **kind-sandboxed coding agents must run inside
  (or be exposed into) the kind cluster.** Mac-local agents can hit either
  side; sandboxed agents only see what the cluster surfaces.
- Components that only serve the **host edge** or that **feed kind itself**
  (Caddy, dnsmasq, the local registry) can stay outside.
- When a component's audience widens to include sandboxed agents, plan its
  move into the cluster. The backplane (section 5) is the first application
  of that trigger.

**The shell-environment policy** (`.zshenv` owns PATH membership,
`.zprofile` re-asserts order after macOS `path_helper`, `.zshrc` owns
interactive-only setup) is stated in `lmde/LMDE.md` and enforced by
`test/smoketest_shell_env.sh`. It is contract, not design-in-flight, and is
not duplicated here.

### 2. Artifact acquisition (`lmde acquire`) and the lmde/clai boundary

`lmde` carries an artifact-acquisition capability distinct from its platform
components. Platform components are laptop-only. Acquisition is the subset
of lmde a cloud sandbox can and should run.

#### 2.1 The axis

> **If it doesn't matter which agent it is, it's lmde. When it matters which
> agent it is, it's clai.**

- **lmde = Acquire.** Fetch and install on-disk artifacts. Agent-agnostic.
  Owns transport, pins, and supply-chain integrity.
- **clai = Configure.** Collate config from layered sources into each
  agent's on-disk form, and set the launch environment. Agent-aware. Owns
  nothing about where artifacts came from.

The two **never call each other and never exchange a data payload.** They
meet only at a set of well-known filesystem locations: lmde installs there,
clai reads from there. That shared path set is the entire contract.

#### 2.2 Responsibility split

| Concern | Owner |
|---|---|
| Fetch skills (`SKILL.md` trees) | **lmde** (the `skills` data package) |
| Fetch the canonical MCP catalog (`mcp/manifest.json`) | **lmde** (ships in the same package) |
| Install MCP server binaries (`ast-mcp`, ...) | **lmde** |
| Install clai itself | **lmde** |
| Version pins + supply-chain integrity gate | **lmde** |
| Collate config layers (catalog <- repo <- user) | **clai** |
| Emit per-agent MCP dialects (`.mcp.json`, `~/.codex/config.toml`, `~/.gemini/config/mcp_config.json`, `opencode.json`) | **clai** |
| Place / symlink skills into each agent's dir | **clai** |
| Register a server at agent scope (`~/.claude.json`) | **clai** |
| ENV / OTel injection at launch | **clai** |

Nothing straddles. (Under the retired template-tools#145 model the first two
rows were owned by neither -- skills rode inside the clai wheel. See History.)

#### 2.3 Contract-by-convention: the locations

The boundary is a small, fixed set of paths **hardcoded in both tools'
code** -- no env vars, no config surface, nothing dynamic. If a path ever
changes, both sides change in the same commit.

| Artifact | Convention path (code constant) | lmde does | clai does |
|---|---|---|---|
| MCP server binaries | `~/.local/bin/<server>` (e.g. `~/.local/bin/ast-mcp`) | installs the binary here | names this path in the emitted config |
| Skills + canonical MCP catalog | `~/.local/lib/node_modules/@nine-at-a-time-media/skills/` | installs the data package here | materializes it into the staging path, then enumerates / collates / places |
| Skills staging (clai-internal) | `~/.cache/clai/template-tools/` | nothing | writes and reads it back |
| clai | on `$PATH` | installs it | is the runtime |

Two rules make the convention load-bearing:

- **lmde installs to convention or not at all.** An artifact either lands at
  its canonical path or is absent; lmde never invents alternate locations
  and never reports paths back to clai.
- **clai reads convention and never gates.** clai uses whatever is present
  and emits config regardless. A missing binary still gets named in the
  config it belongs in; a missing skills dir means zero skills placed, not
  an error. clai never stats an artifact to decide whether to proceed with a
  launch.

The `~/.local/bin/<server>` path was already de-facto load-bearing (the
committed `.mcp.json`, `~/.claude.json`, the `clai.d/*/pre/20-enable-ast-mcp`
hooks, and `install-claude-user.sh` all name `~/.local/bin/ast-mcp`); this
design elevates it from coincidence to contract.

#### 2.4 The package table

`lmde acquire` installs from GitHub Packages (`npm.pkg.github.com`).
Unscoped transitive dependencies resolve from the public registry, because
GitHub Packages serves only scoped packages for the configured owner.

| Shortname | npm package | Ships | Pin key |
|---|---|---|---|
| `skills` | `@nine-at-a-time-media/skills` | DATA (skills tree + MCP catalog + fleet `pins.env`) | `SKILLS_VERSION` |
| `clai` | `@nine-at-a-time-media/clai` | `clai` | `CLAI_VERSION` |
| `ast-mcp` | `@nine-at-a-time-media/ast-mcp` | `ast-mcp` | `AST_MCP_VERSION` |
| `gadmin` | `@nine-at-a-time-media/admin` | `gadmin` | `ADMIN_VERSION` |
| `git-mirror` | `@nine-at-a-time-media/git-mirror` | `git-mirror` | `GIT_MIRROR_VERSION` |

`gadmin` is the one row whose bin name is not its npm name; the shortname
follows the BIN, because `gadmin` is what an agent looks for on `$PATH`.
That row is what makes the `github-workflow` skill's tool ranking true in a
cloud sandbox: without it an agent loses both the `gadmin` tier and the
`gadmin github-gitapi` tier and falls back to the MCP tier the skill rates
at roughly 5-10x the tokens (tds-utils#186).

State lives at `~/.local/state/tds-utils/acquire/<shortname>.version` (the
stamp read by session-start summaries) over an install prefix at
`~/.local/share/tds-utils/acquire/_npm`.

#### 2.5 Pin resolution

Per package, in order:

1. an explicit `--pins <file>` argument;
2. the **fleet pins** shipped inside the acquired skills payload at
   `~/.local/lib/node_modules/@nine-at-a-time-media/skills/pins.env`;
3. float -- resolve the registry's latest published version and install
   THAT concrete version, recording it, so a later run reinstalls on an
   upstream bump. Never an `@latest` tag, which would stamp
   `stamp == target` forever and freeze the package on one release.

The **skills row is processed first and never takes its pin from the fleet
pins of the payload being installed** (self-reference). A `SKILLS_VERSION`
value inside the payload therefore takes effect on the NEXT run at the
earliest; an emergency skills freeze uses an explicit `--pins` file. Loud
either way.

The fleet pins file is the rollout lever: it is committed in template-tools
(`packages/skills/pins.env`), ships in the published payload, and reaches
every surface on its next session via the same floating acquire that
delivers the skills. **A pin bump is a reviewed template-tools PR; the merge
is the rollout.** This closes the two-pins fork -- `tds-utils/sandbox/pins.env`
now gates only the unmigrated bootstrap-and-fetch providers (codex, jules,
copilot; tds-utils#139).

#### 2.6 Degradation

Acquire is fail-open at every step and returns 0 on every path.

| Condition | Behavior |
|---|---|
| No `GH_AI_TOOLS_PAT` | Warn naming the required classic `read:packages` PAT; install nothing; exit 0 |
| Registry unreachable | Keep whatever is installed; warn naming what is stale |
| Package UNREADABLE on the registry (unpublished) | Warn, skip that row, continue the rest |
| Stamp matches but the artifact is gone | Do NOT trust the stamp; reinstall |
| Stamp write fails | Warn; the next run retries |
| `~/.local/bin` not on `$PATH` | Warn. Acquire never edits a shell rc |

The credential is a **classic** PAT with `read:packages` in
`GH_AI_TOOLS_PAT`. Fine-grained PATs have no Packages permission at all, and
the brokered `GH_TOKEN` cannot read GitHub Packages. The npmrc carrying it
is ephemeral and mode 600, and every exit path scrubs it.

#### 2.7 Timing

WHEN acquire runs is deliberately not decided here.
[SANDBOX-LIFECYCLE.DESIGN.md](./SANDBOX-LIFECYCLE.DESIGN.md) is
authoritative: in cloud sandboxes the environment setup script is a CACHE
SEEDER (its work is frozen into a snapshot for up to ~7 days) and the
SessionStart hook is the per-session PROVISIONING AUTHORITY, running
`lmde acquire` then the offline `clai provision`. Acquire is a fast no-op
when current. This document owns WHAT acquire is; that one owns WHEN.

### 3. Observability stack

A local, permanent, hermetic destination for metrics and traces from coding
agents and local services.

#### 3.1 Local container registry

| Responsibility | Details |
|---|---|
| Image mirroring | Pulls upstream images, verifies digests, pushes to `localhost:5001`. Includes the `ingress-nginx` controller and admission-webhook images |
| Digest pinning | All images referenced as `name@sha256:hash` in `images.txt` |
| Lifecycle | Started as a standalone Docker container BEFORE kind, to avoid circularity |

#### 3.2 Infrastructure (kind)

`kind-config.yaml`:

- **Nodes:** 1 control-plane node, labeled `ingress-ready=true` so the
  `ingress-nginx` controller schedules onto it.
- **Port mappings:**
  - node `80` <-> host `127.0.0.1:32100` -- the cluster's single HTTP
    host-edge door, served by `ingress-nginx`.
  - `4317` <-> `4317` (OTLP gRPC), `4318` <-> `4318` (OTLP HTTP).
  - The previous direct `3000` Grafana mapping is REMOVED; Grafana is
    reached through `ingress-nginx`, never a dedicated host port.
- **Mounts:** `~/.local/share/tds-utils/observability/data` -> `/mnt/data`.

#### 3.3 Telemetry pipeline (OTel + Prometheus + Grafana)

- **Helm:** `prometheus-community` and `grafana` charts, templated to use
  local-registry images.
- **Persistence:** HostPath PersistentVolume pointing at `/mnt/data`.
- **Quotas:** a `ResourceQuota` in the `observability` namespace caps CPU at
  1.0 and memory at 2Gi.
- **Grafana Service:** `ClusterIP` only. Dashboards are provisioned from
  `specs/grafana/dashboards/`.

### 4. Host ingress (`*.{cluster}.localhost`)

Bridges the host to in-cluster HTTP services on stable named vhosts. The
pattern is reusable across LMDE clusters:

```
*.{cluster}.localhost  ->  Caddy  ->  ingress-nginx (in {cluster})  ->  Service  ->  pod
```

| Responsibility | Details |
|---|---|
| TLS + host edge | Caddy owns host `:80`/`:443`, terminates TLS for `*.lmde.localhost` (internal CA), reverse-proxies to the cluster's loopback port |
| Cluster routing | `ingress-nginx` routes by `Host` header to the target Service; pod churn is absorbed via EndpointSlices with zero reconfig and no reload |
| Host boundary | One kind `extraPortMapping` publishes ingress-nginx's node port to a per-cluster host loopback port (`127.0.0.1` only) |
| Vhost registration | `lmde/components/networking/lib.sh` registers/updates the Caddy route for `*.{cluster}.localhost` idempotently via the Caddy admin API |

**dnsmasq is not in this path.** `.localhost` resolves to loopback natively,
so a new cluster vhost needs no DNS entry at all -- see
`lmde/components/networking/README.md`, Conventions. dnsmasq stays an Adopted
component for the rest of `.localhost` orchestration and internal service
discovery (`lmde/LMDE.md`), but the ingress pattern does not depend on it.

**Why it scales.** One Caddy route per cluster (not per service); one
`extraPortMapping` per cluster, allocated once at cluster-create time; a new
vhost in an existing cluster is a single `Ingress` object with no host-side
change; a new cluster is one port allocation plus one Caddy route plus an
`ingress-nginx` install.

Because each kind cluster is its own set of Docker containers, two clusters
cannot publish to the same host port. Host ingress ports follow the `3210X`
convention (`X` = cluster index `0`-`9`), drawn from the Kubernetes NodePort
range `30000`-`32767` so they clear common dev ports and stay below the
Linux ephemeral floor (`32768`). The observability cluster is index `0`,
hence `32100`.

### 5. Backplane (NATS-in-kind)

> **Status: DRAFT -- designed, not implemented.** Today NATS runs as a
> standalone host process reachable only at `localhost:4222`, which fails
> the residency rule (section 1) for kind-sandboxed agents.

- **Server:** single-node NATS deployment in the kind cluster. Image
  `nats:2.10.18-alpine`, pinned by digest in the manifest.
- **Storage:** HostPath bind-mount from the Mac host into the kind node
  (`extraMounts` in the cluster config), so JetStream data outlives the kind
  container lifecycle.
- **Host-to-cluster (Mac-local agents):** `nats.lmde.localhost:4222`, TLS
  terminated by Caddy against local CA certs, proxying plaintext TCP to the
  kind NodePort or ingress IP.
- **Cluster-internal (sandboxed agents):** the standard Kubernetes Service
  at `nats.default.svc.cluster.local:4222`, plaintext -- the internal
  network is trusted and the boundary is the host edge.
- **Auth:** move from anonymous loopback to token auth. Source of truth is
  1Password (`op`); tokens are injected into kind as Kubernetes Secrets. To
  avoid an `op` bottleneck on every client, the LMDE bootstrap exports
  `NATS_TOKEN` into a local `.env` for host-side agents.

---

## State Machines

### Observability bootstrap

```
Registry --> Kind Cluster --> Ingress Controller --> Telemetry Stack --> Host Routing --> Readiness
```

| From | To | Trigger | Condition |
|------|-----|---------|-----------|
| START | Registry | `setup.sh` | Docker is running |
| Registry | Kind Cluster | Registry is healthy | `images.txt` is synced |
| Kind Cluster | Ingress Controller | Cluster is Ready | `ingress-ready` node label present |
| Ingress Controller | Telemetry Stack | `ingress-nginx` admission webhook Ready | HostPath dir exists |
| Telemetry Stack | Host Routing | Grafana + Prometheus pods Running | Grafana Service has endpoints |
| Host Routing | Readiness | `Ingress` applied + Caddy vhost registered | `curl grafana.lmde.localhost` returns 200 |

### Acquire, per package

| From | To | Trigger | Condition |
|------|-----|---------|-----------|
| START | SKIPPED | No `GH_AI_TOOLS_PAT` | Warn; nothing installed |
| START | CURRENT | Stamp matches the resolved target | Artifact present at its convention path |
| START | REINSTALL | Stamp matches but artifact missing | Share tree wiped, stamp survived -- stamp is not trusted |
| START | INSTALL | Resolved target differs from stamp | Registry reachable |
| START | DEGRADED | `npm view` fails / package UNREADABLE | Keep what is installed; warn naming the stale row |
| INSTALL | CURRENT | Install succeeds | Stamp written (a failed stamp warns and retries next run) |

---

## Security Considerations

- **Supply chain (platform images).** Local registry plus SHA256 digest
  pinning in `images.txt`; kind nodes pull only from `localhost:5001`.
- **Supply chain (fleet packages).** GitHub Packages only; npm registry
  integrity is ALWAYS on, so `--pins` governs *which version*, never
  *whether it is tamper-checked*. Published versions are immutable. Never
  `curl | sh`, never an integrity-disabling flag.
- **Fleet pins are inert data.** `pins.env` gates executable VERSIONS; the
  executables still arrive pinned and integrity-checked from the registry. A
  tampered pins file cannot inject code that is not a published, verified
  package version.
- **Credential handling.** `GH_AI_TOOLS_PAT` is a classic `read:packages`
  PAT. The npmrc that carries it is ephemeral and mode 600, written only
  into the install prefix, and scrubbed on every exit path including
  INT/TERM/HUP. `--ignore-scripts` on install, so no dependency lifecycle
  script runs with the PAT in its environment.
- **Resource exhaustion.** Kubernetes `ResourceQuota` in the
  `observability` namespace.
- **Data privacy.** All telemetry stays on local disk; no phone-home
  analytics in Grafana or Prometheus.
- **Ingress exposure.** `ingress-nginx` is published only to host loopback
  via the kind `extraPortMapping` `listenAddress`; never bound to a routable
  interface.
- **Backplane auth.** Token auth sourced from 1Password; plaintext is
  confined to the in-cluster network behind the host edge.

---

## Key Decisions

Rows marked SUPERSEDED are retained deliberately: the decision log is
append-only, so a reversed decision gets a row saying so rather than being
deleted.

### Acquisition and the boundary

| Decision | Choice | Rationale |
|---|---|---|
| Split axis | Agent-agnostic acquire (lmde) vs agent-aware configure (clai) | One test decides every responsibility; no straddlers |
| Coupling mechanism | Contract-by-convention (fixed paths) | Loose coupling; either side reimplementable; no runtime handoff to keep in sync |
| Acquisition surface | An `lmde acquire` verb | Names the cloud-portable subset, distinct from platform `lmde install` / `sync` |
| Locations contract | Hardcoded in both tools' code | Nothing dynamic; a path change is one lockstep commit |
| Staging location | Keep `~/.cache/clai/template-tools/` | No churn to the existing clone/symlink layout |
| Receipt / install manifest | Rejected | clai needs none of what it offered; it only re-adds tight coupling |
| clai on a missing artifact | Emit anyway; list dangling refs in a trailing epilogue | Collator, not gatekeeper; the epilogue is a zero-effort debug aid |
| Transport | GitHub Packages npm, no git clone | One rail reachable from both laptop and cloud; kills the Claude-web proxy block |
| Skills delivery | Standalone `@nine-at-a-time-media/skills` data package | Decouples skill freshness from launcher releases; restores code-pinned / data-floats |
| Skills publish trigger | template-tools CI on merge to `main`, path-filtered to `skills/` + `mcp/` | Merge IS rollout; no second manual step to forget |
| Catalog placement | Rides in the skills package | Same inert-data class, same freshness requirement |
| Skills version at acquire | Float to latest | The freshness requirement; `--pins` restores a freeze |
| clai `_data` bundle | Kept as a LOUD bootstrap fallback | Surfaces without acquire still function; removal tracked in Open Questions |
| Mid-session update path | `lmde acquire && clai refresh`, no cross-call | Preserves the never-call-each-other invariant |
| ~~Fleet pins home: `packages/skills/pins.env`, shipped in the skills payload~~ | SUPERSEDED by the engine-sibling row below | Coupled executable version policy to the skills source; moving skills to their own repository would have dragged clai/ast-mcp/gadmin pinning along (PR #243) |
| Fleet pins home | `lmde/lib/pins.env`, a sibling of the acquire engine (vendored twin ships in `@nine-at-a-time-media/sandbox`) | Pins are environment, not skills; the review gate is unchanged -- a pin bump is a reviewed PR (PR #243; body-text reconciliation tracked in issue #249) |
| Pin resolution | explicit `--pins` > fleet pins > float | Explicit stays the emergency override; float stays the no-config default |
| Skills self-reference | The skills row never pins itself from the payload being installed | Otherwise a payload would gate its own delivery; freeze uses an explicit `--pins` file |
| Float semantics | Resolve latest, install and stamp the CONCRETE version | An `@latest` tag would make stamp == target forever and freeze the package |
| gadmin on the rail | Acquire `@nine-at-a-time-media/admin` (bin `gadmin`) | Without it a sandbox agent loses two of three github-workflow tool tiers (tds-utils#186) |
| designomatic on the rail | Acquire `@nine-at-a-time-media/designomatic` (bin `designomatic`; the `dom` alias stays unlinked inside the npm prefix -- one bin per table row) | The provisioned designomatic skill tells agents to run a binary the rail never installed; skills and executables roll out on separate rails, so a skill naming a binary needs a matching table row (shipped in PR #247; table amendment tracked in issue #248) |
| Acquire timing | Session boundary, not only the cache boundary | See SANDBOX-LIFECYCLE.DESIGN.md; the setup stage's work is frozen in a ~7-day snapshot |
| ENV in cloud | Out of scope (launch-time only) | Orthogonal launcher-parity gap G1 |
| ~~Versioning: `latest` by default for every package~~ | SUPERSEDED by the fleet-pins decision | `latest`-by-default gave executables no review gate; the fleet pins restore it without a second on-disk edit |
| ~~Skills + catalog ride inside the `@clai` package (`clai/_data`), template-tools#145~~ | SUPERSEDED | Made a skill rollout a two-step human process (clai release + `CLAI_VERSION` bump); measured failure, see History |
| ~~Skills pinned to the resolved clai version; a skill rollout is a clai release + pin bump~~ | SUPERSEDED | Same failure; skills float as their own package |

### Observability and ingress

| Decision | Choice | Rationale |
|---|---|---|
| Storage | HostPath mapping | Simplest path to survival across cluster deletes in kind |
| In-cluster HTTP routing | `ingress-nginx` | A controller, not a config file: routes by `Host` to Services, absorbs pod churn with zero reconfig, one mechanism scales to many vhosts |
| Host-to-cluster path | One kind `extraPortMapping` per cluster -> ingress-nginx hostPort | Each kind cluster is isolated Docker containers; a unique host loopback port per cluster is the only stable door |
| Ingress host port | `3210X` (X = cluster index `0`-`9`); observability = `32100` | Inside the NodePort range `30000`-`32767`: clear of common dev ports, below the Linux ephemeral floor |
| Vhost scheme | `*.{cluster}.localhost` (this cluster aliased `lmde`) | `.localhost` resolves to loopback with no dnsmasq config; a per-cluster wildcard keeps it to one Caddy route |
| Registry | `Registry:2`, standalone container | Avoids the circular dependency where the cluster is needed to start the registry |
| Deployment | Helm charts with local-registry images | Community config best-practice while keeping image control |

### Backplane

| Decision | Choice | Rationale |
|---|---|---|
| NATS residency | In-cluster, not host-exposed | Simplifies residency for sandboxed agents and unifies infrastructure lifecycle |
| NATS host edge | Caddy TCP proxying, not `ingress-nginx` TCP snippets | Keeps one host edge; Caddy already owns `.localhost` TLS and DNS |
| NATS persistence | kind `extraMounts` host bind-mount | JetStream data outlives the kind container lifecycle |

---

## Open Questions

1. **`clai/_data` end state** -- once every surface is on
   acquire-then-configure, is the bundled fallback removed outright? Removal
   kills the dual-source staleness risk this design otherwise leaves as a
   warned fallback.
2. **Dangling-config benignness across agents** -- an emitted config naming
   an absent binary must be inert for codex / agy / opencode as it is for
   Claude Code. The trailing epilogue surfaces these; confirm none of the
   four errors rather than skipping.
3. **Pins-file scope** -- `--pins <file>` pins every artifact the file names
   and floats the rest; confirm nothing needs pinning that the file cannot
   express (e.g. a transitive dep of a floated package).
4. **Unpublished rails** -- `git-mirror` and `sandbox-qol` resolve
   UNREADABLE on the registry (measured 2026-08-13), so their rows degrade
   fail-open on every run. Publish or drop them (tds-utils#188,
   template-tools#428).
5. **Skills package version scheme** -- CI auto-patch (current) vs CalVer
   (encodes rollout date, nonstandard semver).
6. **Dashboard provisioning** -- default dashboards for coding agents ship
   from `specs/grafana/dashboards/`; which set is the default is open.
7. **OTel sampling** -- default sampling rate to bound storage growth.
   Currently 100% for development.
8. **Backplane migration path** -- is there JetStream data on the host that
   must be migrated, or can NATS-in-kind start clean? (Recommendation: clean
   slate for the MVP.)

---

## Rejections

### Acquisition

- **A receipt / install manifest handed from lmde to clai.** The path is a
  convention (no data needed) and version + currency are Acquire's concern;
  the receipt bought clai nothing and re-created the exact producer ->
  consumer coupling the split exists to remove.
- **clai gating a launch on artifact presence.** clai is a collator; a
  missing server is the agent's problem to report, not clai's to block on.
- **Keeping acquisition in clai "because it already works on the laptop."**
  It works on the laptop and is precisely what fails in the cloud; leaving
  it blurs the concern split and keeps clai coupled to transport.
- **Return to a git clone of template-tools at provision time.** The
  Claude-web proxy brokers only the session's own repo; the block that
  killed this is unchanged.
- **Automating clai releases on skill merges (keeping the bundle).** Still
  couples launcher version churn to prose edits, and a launcher rollback
  would silently roll back skills.
- **Committing skills into each consuming repo.** The drift this whole
  system exists to kill.

### Observability and ingress

- **Istio (service mesh).** Its ingress gateway is itself an in-cluster
  Service, so it inherits the same host-boundary problem without removing
  it, while adding istiod, sidecars, and CRDs. Mesh features are a Non-Goal.
- **Direct NodePort per service, no ingress controller.** Works for one
  service, but every new vhost needs a new NodePort AND a new
  `extraPortMapping` -- and those are frozen at cluster-create time, so each
  new service would force a cluster recreate.
- **In-cluster ingress as the host edge (skip Caddy).** Caddy is the
  platform's single host reverse proxy and TLS terminator; the cluster sits
  behind it on a loopback port rather than competing for host `:80`/`:443`.
- **Dynamic provisioning (EBS/GCP volumes).** Not applicable to a local
  laptop.
- **Local registry as a pod.** Circular dependency.

### Backplane

- **`ingress-nginx` TCP snippets for NATS.** Avoids a split-brain edge
  between Caddy and Ingress.
- **Raw HostPath (no bind-mount).** Data is lost on cluster recreation.

---

## Future Considerations

- **Alerting** -- macOS notifications via a custom exporter.
- **Tracing** -- Tempo (or Jaeger) once traces matter as much as metrics;
  the Loki events leg is the nearer-term addition.
- **Generic cluster-ingress mechanism** -- the `*.{cluster}.localhost`
  pattern is implemented in `lmde/components/networking/` for the
  observability cluster. When a second LMDE cluster appears, promote it to a
  reusable `register_cluster_vhost` helper with a host-port allocation
  registry, in its own design doc.
- **Cluster rename** -- the vhost alias is `lmde` while the kind cluster is
  `lmde-observability`. Aligning them is cosmetic and deferred.
- **Approach B for MCP servers** -- npx-spawned servers acquiring at spawn
  time, closing the N-1 binary freshness window. Tracked in
  SANDBOX-LIFECYCLE.DESIGN.md and tds-utils#219.
- **Provider migration** -- mapping the seed/authority split onto Codex,
  Jules, and Copilot wrappers (tds-utils#139); until then
  `sandbox/pins.env` remains their lever.

---

## History (superseded revisions)

Kept so the reasoning is not relitigated. Each of these was a real
measured failure, not a preference change.

**template-tools#145 -- skills bundled inside the clai wheel.** Adopted to
escape the cloud git-clone block: skills and the MCP catalog shipped as
`clai/_data` inside the `@clai` package, `GitSourceFetcher` was deleted, and
clai materialized the bundle offline. The rail it built (GitHub Packages,
registry integrity, no clone) is still in use. What failed was the delivery
model on top of it.

**Revision 1 (2026-07-30) -- skills decoupled from the clai release.** The
#145 model made a skill rollout a two-step human process: cut a clai
release, then bump `CLAI_VERSION`. Nothing enforced either step. Measured in
a live cloud sandbox: the skills tree gained `sdlc` and `lmde-dashboards`
and three repos' AGENT.md files referenced `sdlc`, but no clai release
followed -- every environment provisioned 15 of 17 skills, and the skill the
docs pointed at was loadable nowhere. Independently, the installed clai
(0.6.0) lagged its pin (0.7.0). Nothing flagged either gap. Skills became
their own floating data package, restoring the original stance:
**executables pinned, inert data floats.** The structural property gained is
that publishing is a CI effect of the merge that changed the skill, so the
skills tree can never again sit ahead of the newest published package.

**Revision 2 (2026-08-13) -- acquire moves to the session boundary.** The
sandbox reflow assumed the environment setup script ran per session. It runs
once per snapshot-cache build (~7 days), so everything acquired at setup --
packages AND pins -- was frozen for the cache window and Revision 1's
freshness requirement was structurally unmet. The session itself holds the
PAT and reaches npm.pkg.github.com, so the constraint that pushed
acquisition into the setup stage no longer existed. Nothing structural
changed: the two tools still never call each other, and no convention path
moved. Full detail in SANDBOX-LIFECYCLE.DESIGN.md.

---

## Related Documents

- [`lmde/LMDE.md`](../../lmde/LMDE.md) -- the runtime contract: Adopted
  components, residency, shell-environment policy.
- [`lmde/TECH_RADAR.md`](../../lmde/TECH_RADAR.md) -- repo-scoped radar data
  (human-maintained).
- [SANDBOX-LIFECYCLE.DESIGN.md](./SANDBOX-LIFECYCLE.DESIGN.md) --
  authoritative for WHEN acquire runs on cloud surfaces.
- [PROVISION.DESIGN.md](./PROVISION.DESIGN.md) -- the historical unified
  provisioning design this boundary split at step two; RD8 records the stage
  semantics.
- template-tools `packages/clai/docs/CLAI.DESIGN.md` -- the configure half
  of the boundary.
- [`test/smoketest_lmde_clai/`](../../test/smoketest_lmde_clai/) -- the
  black-box behavioral smoketest for the boundary. It stands inside a real
  laptop or cloud session and asserts the observable convention locations
  the split promises, without caring which tool placed them.
- [`test/smoketest_lmde_acquire/`](../../test/smoketest_lmde_acquire/) --
  the acquire engine's own suite.
- [`test/smoketest_lmde_observability/`](../../test/smoketest_lmde_observability/)
  -- the observability stack's bootstrap suite.
- `sandbox/README.md` -- the provider wrapper tree that invokes acquire.
