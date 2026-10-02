# Ollama Gateway

> **Status:** DRAFT  
> **Date:** 2026-10-02  
> **Authors:** Todd Stumpf, Claude (Opus 5.5)  
> **Depends on:** [LMDE](./LMDE.DESIGN.md); tds-internal `ops/terraform/ollama-gateway` (its own design record, written alongside this one)  
> **Origin:** [concept: ollama-gateway](../concepts/ollama-gateway/CONCEPT.md), issue #363

---

## Overview

The Ollama Gateway is an LMDE sub-component that lets an authorized caller
off the laptop -- first, a GitHub Actions run of Open Code Review -- get
completions from a model on the laptop. It is a Cloudflare Access-protected
cloudflared tunnel in front of a second, external-facing ollama that runs
inside the macOS sandbox, so nothing arriving over the tunnel can read the
user's credentials -- `~/.ssh`, AI tool credentials, or anything else in the
home directory outside an allow-listed tree.

---

## Goals

- **G1 Authorized completions.** A caller presenting a valid gateway
  credential to `https://<gateway-host>/v1/chat/completions` gets a
  completion from a model in the laptop's store, and `GET /v1/models` lists
  those models.
- **G2 Nobody else gets in.** A request without a valid gateway credential
  is refused at the Cloudflare edge (HTTP 403) and never reaches the
  laptop: the external ollama's request log shows no entry for it.
- **G3 Completions only.** Any request path other than `/v1/chat/completions`
  and `/v1/models` gets HTTP 404 from the tunnel and never reaches the
  external ollama -- `/api/pull`, `/api/delete`, `/api/create`,
  `/api/push` and the rest included.
- **G4 The external ollama cannot read the user's credentials.** It runs
  inside a macOS sandbox whose home-directory rule is an allow-list: the
  external ollama process and every process it spawns can read or write
  under `$HOME` only within the allow-listed trees -- the gateway's own
  user config tree and the model store. Everything else under `$HOME` is
  denied, which covers `~/.ssh`, AI tool credentials (`~/.claude`,
  `~/.codex`, `~/.config/gh`, and the like), 1Password data, and ollama's
  own identity key `~/.ollama/id_ed25519`. The denial is asserted by a
  smoketest that runs the profile against a probe reading those paths, not
  inferred from the profile text. Outside `$HOME` the first-cut sandbox may
  be broad; tightening it is a later hardening pass (Future
  Considerations).
- **G5 Outages fail fast.** With the laptop asleep, offline, or the
  connector stopped, a request is answered by the Cloudflare edge with an
  HTTP 5xx within 30 seconds; it never hangs. With the connector up but the
  external ollama down, the connector answers HTTP 502 within 5 seconds.
- **G6 Everything is IaC.** Every Cloudflare resource and every credential
  on the road -- tunnel, DNS, Access application and policy, service
  tokens, and the 1Password items holding them -- is declared in
  tds-internal terraform. The single exception is the 1Password service
  account, which terraform cannot create (tds-internal
  `docs/policy/CREDENTIALS.md`).
- **G7 Runs unattended.** Both laptop daemons start at login and restart
  after a crash, without a human, and without 1Password being unlocked.
- **G8 The everyday ollama is untouched.** `127.0.0.1:11434`, its
  configuration, its LaunchAgent and its loaded models are unchanged by
  installing, running or removing the gateway.

---

## Non-Goals

- **Running `ocr` (or any caller) on the laptop.** Callers run elsewhere;
  `ocr` is untrusted and never runs on the laptop except containerized,
  which is out of scope for the POC and MVP (concept, settled).
- **Isolating the credential from the caller.** In the first cut the
  caller holds the gateway credential and could carry it off. Deferred to
  issue #365 by Todd's ruling.
- **Per-owner credentials.** The first cut shares one service token and one
  1Password service account across both GitHub owners. The seam for the
  split exists (see Credential contract); the split does not.
- **Model management through the gateway.** No pull, delete, create or
  copy. Models are added to the store by the everyday ollama, by hand.
- **A nonprod tier.** There is one laptop and one model store; a second
  tier would point at the same hardware.
- **Availability guarantees.** The gateway is up when the laptop is up.
  No failover, no queueing at the edge, no retries.
- **Rate limiting or quotas.** ollama's own request queue is the only cap.
- **A public model API.** Only callers named in tds-internal get a
  credential.

---

## Architecture Overview

```
 caller (e.g. ocr-on-demand on a GitHub runner)
   |  HTTPS to <gateway-host>, with the gateway credential as headers
   v
+----------------------------- Cloudflare (api9 account) ---------------+
|  Access application on <gateway-host>                                 |
|    policy: non_identity, includes exactly the named service tokens    |
|  Tunnel (remotely managed; ingress declared in tds-internal IaC)      |
|    /v1/chat/completions, /v1/models  -> http://127.0.0.1:<port>       |
|    anything else                     -> 404                           |
+-----------------------------------------------------------------------+
   |  outbound-only connection, initiated by the laptop
   v
+------------------------------- laptop --------------------------------+
|  connector daemon (cloudflared, LaunchAgent)                          |
|        |  loopback only                                               |
|        v                                                              |
|  +-------------------- macOS sandbox profile ----------------------+  |
|  |  external ollama (LaunchAgent), 127.0.0.1:<port>                 |  |
|  |    HOME = gateway config tree                                    |  |
|  |    $HOME allow-list: gateway config tree + model store only      |  |
|  +------------------------------------------------------------------+  |
|                                                                       |
|  everyday ollama, 127.0.0.1:11434 -- unchanged, not on the road       |
|  model store (~/.ollama/models) -- written only by the everyday one   |
+-----------------------------------------------------------------------+

 IaC (tds-internal ops/terraform/ollama-gateway) declares everything in the
 Cloudflare box plus the credentials; tds-utils lmde/components/ declares
 everything in the laptop box. Dependencies point from the edges to the
 contract (host, credential headers, paths), never from a caller to
 Cloudflare specifics.
```

---

## Design

### Edge (tds-internal IaC)

Declared in tds-internal `ops/terraform/ollama-gateway/`, following the
`ops/terraform/quillmap-smoketest` service-token pattern. Its own design
record in tds-internal owns the module's internals; this section states
what the gateway relies on.

#### Responsibilities

| Responsibility | Guarantee the gateway relies on |
|---|---|
| Tunnel | Remotely managed: the ingress rules live in IaC, not in a file on the laptop |
| Ingress allow-list | Exactly two path rules route to `http://127.0.0.1:<port>`; a catch-all returns 404 (G3) |
| DNS | `<gateway-host>` routes to the tunnel |
| Access application | Covers all of `<gateway-host>`; no bypass paths |
| Access policy | `decision = non_identity`, including exactly the named service tokens -- never `any_valid_service_token` |
| Service tokens | One per consumer, from a `for_each` map; dropping a key revokes that consumer |
| Credentials at rest | Each service token's client id and secret, and the tunnel's run token, land in 1Password items, never directly in a GitHub secret |

#### API / Interface

```
POST https://<gateway-host>/v1/chat/completions   (OpenAI-compatible)
GET  https://<gateway-host>/v1/models

Request headers (the gateway credential):
  CF-Access-Client-Id:      <service token client id>
  CF-Access-Client-Secret:  <service token client secret>

Responses:
  2xx    the external ollama's response, unmodified
  403    missing or invalid credential (Access)
  404    any other path (tunnel ingress)
  502    connector up, external ollama down
  5xx    connector not connected (laptop asleep/offline)
```

### Credential contract

What a caller needs to know to use the gateway, and the seam that lets
owners be split later.

| Item | Value |
|---|---|
| 1Password item title | `ollama-gateway-<consumer>` |
| Fields | client id, client secret (field names fixed by the tds-internal module) |
| Vault | a headless vault, read by a read-only 1Password service account scoped to that vault |
| Consumers in the first cut | one: `gha`, shared by the 9atatimer and Nine-At-A-Time-Media owners |

The vault is the per-owner seam. A caller resolves the vault from its own
configuration, never from a constant; in the first cut every owner's
configuration names the same vault. Splitting an owner off later is a new
`for_each` key, a new vault and service account, and a configuration
change on that owner -- no change to the gateway, and none to any caller's
code. How a caller resolves its vault is the caller's design
([OCR on Demand](./OCR-ON-DEMAND.DESIGN.md), to be written).

### Connector daemon (tds-utils LMDE)

#### Responsibilities

| Responsibility | Details |
|---|---|
| Hold the tunnel open | Runs `cloudflared` with the tunnel's run token, outbound only |
| Transport | `http2`. QUIC over IPv6 fails on this network (observed on the existing `foundry-isleofmist` tunnel), so the transport is pinned |
| Start and restart | A LaunchAgent following the LMDE pattern (`macos/launchd/com.tds.<name>.plist` -> `bin/launch-<name>`, listed in a `packages/*.pkg` `SERVICES`, installed by `bin/tds-install -S`), with restart on crash |
| Keep the run token out of sight | The token never appears on a process command line or in a file under the repo; it is read from the laptop's credential store at launch (store: Open Question Q2) |
| Refuse to run half-configured | No token, no start: the launcher exits non-zero with a message naming what is missing |

The connector is not sandboxed in the first cut: it is a trusted vendor
binary installed by Homebrew, and it must reach the network. See Future
Considerations.

### External ollama (tds-utils LMDE)

#### Responsibilities

| Responsibility | Details |
|---|---|
| Serve completions | `ollama serve` bound to `127.0.0.1:<port>` only; `<port>` is distinct from the everyday 11434 |
| Run sandboxed | Launched under the gateway's macOS sandbox profile (G4). The profile is a file in the component, and its `$HOME` denials are smoketested |
| Own config tree | `HOME` is the gateway's user config tree under `~/.local/` (exact path is code), not the user's home, so ollama never touches `~/.ollama/id_ed25519` (its ollama.com identity key) or `~/.ollama/history` |
| Shared store | `OLLAMA_MODELS` points at the everyday store, the second allow-listed tree. Model management cannot reach it over the road (G3) |
| Bounded memory | Holds at most one model loaded at a time, so the external and everyday instances together cannot load an unbounded set into the laptop's 64 GB |
| Start and restart | A LaunchAgent, same pattern as the connector, restart on crash |

The 2026-10-02 spike (issue #363) showed this works: under such a profile,
ollama 0.34.4 found the Metal GPU, listed all 23 models read-only, served
`/v1/chat/completions` at 100% GPU, failed to pull (no DNS), and the
profile denied reads of `~/.ssh` and `~/.ollama/id_ed25519`.

One part of the sandbox profile is load-bearing: inside `$HOME` it is an
allow-list -- the gateway's config tree and the model store, nothing else
-- because that is what keeps credentials out of reach. The rest of the
profile may be broad in the first cut; its exact text is code, and
hardening it (network, store writes, system paths) is handed to a later
pass once the POC runs.

---

## State Machine

The gateway's state as a caller sees it, composed from the two daemons and
the edge. The daemons themselves are launchd-managed (started at login,
restarted after a crash); the states below are what a request meets.

```
                connector connects
 +-------------+ ---------------------> +-------------+
 | UNREACHABLE |                        |  CONNECTED  |
 +-------------+ <--------------------- +-------------+
       ^          connector disconnects    |      ^
       |          (sleep, offline, crash)  |      |
       |                     ollama down   |      | ollama up
       |                                   v      |
       |                                +-------------+
       +------------------------------- |  DEGRADED   |
            connector disconnects       +-------------+
```

| State | Edge answers a credentialed request with | Within |
|---|---|---|
| UNREACHABLE | HTTP 5xx from Cloudflare (tunnel has no connector) | 30 s |
| CONNECTED | the external ollama's response | model-dependent; cold load of a ~23 GB model measured at 1m48s |
| DEGRADED | HTTP 502 from the connector | 5 s |

| From | To | Trigger |
|---|---|---|
| UNREACHABLE | CONNECTED | connector establishes the tunnel and the external ollama is listening |
| CONNECTED | UNREACHABLE | laptop sleeps, goes offline, or the connector exits |
| CONNECTED | DEGRADED | external ollama exits or stops listening |
| DEGRADED | CONNECTED | launchd restarts the external ollama |
| DEGRADED | UNREACHABLE | connector disconnects |

Credential and path checks (G2, G3) apply in every state: a request without
a valid credential gets 403, and a non-allow-listed path gets 404, whether
or not the laptop is reachable.

---

## Data Model

No database. Two declared structures:

```
consumers (tds-internal terraform for_each map)
+-- key                 consumer name, e.g. "gha"; dropping it revokes
+-- -> service token    one per key
+-- -> Access policy    non_identity, includes only that token
+-- -> 1Password item   ollama-gateway-<key>: client id, client secret

laptop component (tds-utils lmde/components/ollama-gateway)
+-- sandbox profile     the external ollama's policy file
+-- port                external ollama's loopback port (not 11434)
+-- gateway config tree the external ollama's HOME, under ~/.local/
+-- model store path    the everyday store; the other allow-listed tree
```

---

## Data Warehouse

Nothing is ledgered. The gateway is a pipe; what flowed through it, and how
often reviews failed, is the caller's to record (OCR on Demand owns review
outcomes and error rates).

---

## Security Considerations

- **Unauthenticated callers.** Refused at the Access edge (G2). The policy
  names each token; `any_valid_service_token` would admit every service
  token in the account, so it is forbidden.
- **A credentialed caller trying to manage models.** The tunnel routes only
  the two completion paths (G3), so `/api/pull`, `/api/delete` and the
  rest never reach the external ollama. In the first cut that is the only
  layer; denying store writes and outbound network in the sandbox is part
  of the hardening pass.
- **A hostile prompt or model exploit in the inference engine.** The
  sandbox's `$HOME` allow-list keeps the user's credentials out of reach
  -- `~/.ssh`, AI tool credentials, 1Password data, ollama's identity key
  (G4). Until the hardening pass, a compromised engine could still reach
  the network and paths outside `$HOME`; it could not read what is worth
  stealing in the home directory.
- **Tool calls.** ollama returns a model's tool calls to the caller; it
  never executes them. A caller's tools run on the caller's machine, never
  on the laptop.
- **Credential theft by the caller.** In the first cut the caller holds the
  gateway credential and could exfiltrate it; whoever holds it can then
  get completions (but no more -- G3, G4 still hold). One shared token
  means one leak exposes the road for both owners. Accepted for the first
  cut; issue #365 tracks isolation. Revocation is dropping the consumer
  key and re-applying.
- **The tunnel run token.** Whoever holds it can impersonate the laptop's
  connector. It lives in 1Password (IaC) and in the laptop's credential
  store, never on a command line, in the repo, or in a LaunchAgent plist.
- **Prompt and completion contents.** They cross Cloudflare's edge, TLS
  terminated there. Acceptable for code under review in the fleet's own
  repos; no other data is intended to use the road.
- **Crossing the LMDE "never routable" non-goal.** This is the one
  deliberate public ingress. It is bounded by G2, G3 and G4, and recorded
  as a Key Decision here and as an appended Key Decisions row in
  `LMDE.DESIGN.md`.
- **sandbox-exec is deprecated by Apple** but functional on this macOS.
  If a macOS update removes or weakens it, G4's smoketest fails and the
  external ollama must not start. See the radar row.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the gateway lives | An LMDE sub-component, separate from any caller | Todd (concept, settled): a further evolution of our use of ollama, its own domain |
| Who declares cloud resources and credentials | tds-internal terraform, all of them | Todd (concept, settled): all IaC and all credentials live in tds-internal |
| Who runs the laptop daemons | tds-utils LMDE, launchd pattern | Todd (concept, settled) |
| Which ollama is on the road | A second, external-facing instance, never the everyday one | Todd (concept, settled): the external ollama is a security domain; the everyday one keeps its identity key, history and network |
| How the external ollama is confined | The basic macOS sandbox (`sandbox-exec` profile) | Todd (concept, settled): start with the basic Mac sandbox. Spike 2026-10-02 shows GPU inference works under it; Docker on macOS has no Metal GPU |
| Sandbox policy scope, first cut | Load-bearing: `$HOME` is an allow-list (the gateway's user config tree under `~/.local/`, plus the model store). Everything else may be broad | Todd (2026-10-02): protect `~/.ssh`, AI creds and such with a whitelist of a user config tree; get it running in any sandbox first, and hand hardening to a smarter model after the POC works |
| Model files | Shared everyday store, the external instance's second allow-listed tree | No second copy of tens of GB; G3 keeps model management off the road, and the hardening pass makes the store read-only |
| Tunnel config | Remotely managed, ingress in IaC | The path allow-list is a security control (G3) and belongs in reviewed IaC, not a laptop file |
| Path exposure | Allow-list: `/v1/chat/completions`, `/v1/models`; 404 otherwise | ollama has no auth and exposes model-management endpoints |
| Access policy | `non_identity`, naming each token | Revocable per consumer; `any_valid_service_token` admits every token in the account |
| Credentials for the first cut | One service token, one 1Password service account, shared by both GitHub owners | Todd's ruling (PR #364) |
| Per-owner axis of change | Seam = the vault a caller resolves from its own configuration; tokens are a `for_each` map | Splitting owners later needs no gateway or caller code change |
| Caller isolation from the credential | Not in the first cut | Todd's ruling on codex review, PR #364; issue #365 |
| Transport | `http2` | QUIC over IPv6 fails on this network |
| Edge vendor axis | Seam = the caller contract (URL + credential headers + paths) | Callers depend on the contract, never on Cloudflare specifics; swapping the edge changes IaC and the connector only |
| Model choice | Not the gateway's: callers name a model; the gateway serves the store | The model is a caller detail (concept: "whatever gets it done") |
| Radar: cloudflared | Propose Trial, in `lmde/TECH_RADAR.md` and tds-internal `docs/TECH_RADAR.md` | Todd (concept, settled). Exit: the gateway runs a month without a manual restart |
| Radar: macOS sandbox (`sandbox-exec`) | Propose Trial in `lmde/TECH_RADAR.md` | Apple-deprecated API; Trial until a supported replacement is chosen or it proves stable across a macOS major update |
| LMDE "Public ingress" non-goal | Crossed for this one endpoint; append a Key Decisions row to `LMDE.DESIGN.md` citing this record and issue #363 | The LMDE record is frozen; its log is append-only |

---

## Open Questions

- **Q1 Hostname and tier.** Proposed: `ollama.api9.com`, production tier
  only (bare `<service>.<zone>` per the naming rule). `api9.com` is the
  zone of Todd's own account. Needs Todd's confirmation.
- **Q2 Where the connector's run token lives on the laptop.** The daemon
  must start while 1Password is locked (G7). Proposed: the macOS login
  Keychain, seeded once from the 1Password item by a setup step and read at
  launch, so it never lands on a command line or in a plist. Alternative:
  cloudflared's own credentials file under the gateway's private directory,
  mode 600.
- **Q3 Memory contention.** Two ollama servers on one 64 GB laptop can each
  hold a large model. Bounding the external instance to one loaded model
  (Design) caps it, but the everyday instance is unbounded. Is that enough,
  or should the external one also unload promptly after each review?
- **Q4 The name.** "Ollama Gateway" is the working name from the concept.

---

## Rejections

- **Expose the everyday ollama on 11434 directly.** It holds ollama's
  identity key and history, has network, and can manage models; the
  concept requires a separate, sandboxed external instance.
- **Run the external ollama in Docker.** Docker on macOS has no Metal GPU;
  inference would fall back to CPU.
- **Locally managed tunnel config (`~/.cloudflared/config.yml`).** It
  would put the path allow-list -- a security control -- in an unreviewed
  laptop file.
- **Reuse the existing `foundry-isleofmist` tunnel.** It belongs to the
  GammaGo Cloudflare account and another system; a new system gets its own
  credentials, never a borrowed one (tds-internal policy).
- **`any_valid_service_token` in the Access policy.** Admits every service
  token in the account, and cannot revoke one consumer.
- **Expose all ollama paths and rely on the sandbox alone.** In the first
  cut the sandbox does not deny store writes or network, so the path
  allow-list is what keeps model management off the road; after hardening
  it stays as a second layer.
- **Per-owner service tokens and service accounts in the first cut.**
  Todd's ruling: POC with one; the vault seam keeps the split cheap later.
- **A GitHub App for the caller's Cloudflare credential.** It solves
  GitHub-side identity, not Cloudflare's.
- **An SSH reverse tunnel or Tailscale Funnel instead of cloudflared.**
  Todd settled on cloudflared and Access; tds-internal already has the
  Access service-token pattern and its IaC.
- **A nonprod tier.** One laptop, one store: it would test nothing the
  production tier does not.
- **Sandboxing the connector in the first cut.** It needs the network, is
  a signed vendor binary, and sees only what the tunnel routes.

---

## Future Considerations

- **Sandbox hardening pass** -- after the POC runs, a stronger model
  reviews and tightens the profile: outbound network limited to loopback,
  model store read-only, system paths narrowed. The 2026-10-02 spike
  showed the network and home denials do not break GPU inference.
- **Credential isolation from the caller** -- issue #365.
- **Per-owner credentials** -- one consumer key, vault and service account
  per GitHub owner, when the first cut has proven the road.
- **Sandboxing the connector**, limiting it to its config and loopback.
- **Gateway metrics in the LMDE observability stack** -- connector state
  and request counts, if review error rates point at the gateway.
- **A supported successor to sandbox-exec**, should Apple remove it.
- **More callers** -- each is a new consumer key; the contract does not
  change.

---

## Related Documents

- [LMDE](./LMDE.DESIGN.md) -- the platform this is a sub-component of; its
  "Public ingress" non-goal is crossed here for one endpoint
- [concept: ollama-gateway](../concepts/ollama-gateway/CONCEPT.md) -- origin
  (non-binding)
- [concept: ocr-on-demand](../concepts/ocr-on-demand/CONCEPT.md) -- the
  first caller's concept
- OCR on Demand (`OCR-ON-DEMAND.DESIGN.md`, to be written) -- the first
  caller; owns vault resolution and review outcomes
- tds-internal `ops/terraform/quillmap-smoketest` -- the service-token
  pattern the edge follows
- tds-internal `docs/policy/CREDENTIALS.md`, `INFRASTRUCTURE.md`,
  `TERRAFORM.md` -- the rules the edge obeys
- [REMOLLAMA](./REMOLLAMA.DESIGN.md) -- the opposite direction (laptop
  reaching a rented GPU); unrelated mechanism
