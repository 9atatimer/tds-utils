# Ollama Gateway

> **Status:** REVIEW  
> **Date:** 2026-10-02  
> **Authors:** Todd Stumpf, Claude (Opus 5.5)  
> **Depends on:** [LMDE](./LMDE.DESIGN.md); tds-internal `ops/terraform/ollama-gateway` (its own design record, written alongside this one; not yet written)  
> **Origin:** [concept: ollama-gateway](../concepts/ollama-gateway/CONCEPT.md), issue #363

---

## Overview

The Ollama Gateway is an LMDE sub-component that lets an authorized caller
off the laptop get completions from a model on the laptop. The first caller
is a GitHub Actions run of Open Code Review. The gateway is a Cloudflare
Access-protected cloudflared tunnel in front of a second, external-facing
ollama. That ollama runs inside the macOS sandbox, so nothing arriving over
the tunnel can read the user's credentials: `~/.ssh`, AI tool credentials,
or anything else in the home directory outside an allow-listed tree.

---

## Goals

- **G1 Authorized completions.** A caller presenting a valid gateway
  credential to `https://<gateway-host>/v1/chat/completions` gets a
  completion from a model in the laptop's store, and `GET /v1/models` lists
  those models. This holds for any request whose first response byte
  arrives within the edge's proxy time-to-first-byte limit. How a cold
  model load that exceeds that limit is handled is Open Question Q5, and Q5
  blocks APPROVED.
- **G2 Nobody else gets in.** A request without a valid gateway credential
  is refused at the Cloudflare edge, whatever its path, and never reaches
  the laptop. The refusal is a redirect to the Access login page (HTTP 302)
  or HTTP 403, never a 2xx. The external ollama's request log shows no
  entry for it.
- **G3 Completions only.** A credentialed request reaches the external
  ollama only if its path is exactly `/v1/chat/completions` or
  `/v1/models`. No prefix or substring match is admitted. Any other path
  gets HTTP 404 from the tunnel's ingress rules and never reaches the
  external ollama. This includes `/api/pull`, `/api/delete`, `/api/create`,
  `/api/push` and the rest. The checks run in order: Access first (G2),
  then ingress.
- **G4 The external ollama cannot read the user's credentials.**
  - It runs inside a macOS sandbox whose home-directory rule is an
    allow-list. The external ollama process, and every process it spawns,
    can read or write under `$HOME` only within the allow-listed trees: the
    gateway's own user config tree and the model store.
  - Everything else under `$HOME` is denied. Key examples are `~/.ssh`, AI
    tool credentials (`~/.claude`, `~/.codex`, `~/.config/gh`), 1Password
    data and ollama's own identity key `~/.ollama/id_ed25519`.
  - The connector's run token (Q2) is unreachable from inside the sandbox
    by any means, not only by path.
  - Both properties are asserted by a probe that runs under the profile.
    They are not inferred from the profile text. The probe's acceptance
    criteria are:
    - a canary file under `$HOME`, outside both allow-listed trees, is
      unreadable;
    - every means the launcher itself uses to retrieve the run token
      fails.
  - Outside `$HOME`, the first-cut sandbox may be broad. Security
    Considerations names what that admits. Tightening it is a later
    hardening pass (Future Considerations).
- **G5 Outages fail fast.** No outage makes a request hang.
  - With the connector stopped, the Cloudflare edge answers a request with
    HTTP 5xx within 30 seconds.
  - With the laptop asleep or offline, the bound depends on how fast the
    edge detects a silent connector. That bound is unverified (Q6).
  - With the connector up but the external ollama down, the connector
    answers HTTP 502 within 5 seconds.
- **G6 Everything is IaC.** Every Cloudflare resource and every credential
  on the road is declared in tds-internal terraform. That means the tunnel,
  DNS, the Access application and policy, the service tokens, and the
  1Password items holding them.
  - There is one exception: the 1Password service account, which terraform
    cannot create (tds-internal `docs/policy/CREDENTIALS.md`).
  - The laptop's local copy of the run token is seeded from its 1Password
    item. It is not a separately minted credential.
- **G7 Runs unattended.** Both laptop daemons start at login and restart
  after a crash. Neither needs a human, and neither needs 1Password to be
  unlocked. A failing G4 probe is not a crash: it holds the gateway
  DEGRADED until a human acts (State Machine).
- **G8 The everyday ollama is untouched.** In normal operation, installing,
  running or removing the gateway leaves these unchanged:
  `127.0.0.1:11434`, its configuration, its LaunchAgent, its loaded models,
  and the contents of the model store it manages. Under compromise of the
  external engine, G8 is not guaranteed until the hardening pass denies
  store writes and loopback reach to 11434. That is an accepted risk
  (Security Considerations, Q7).

---

## Non-Goals

- **Running `ocr` (or any caller) on the laptop.** Callers run elsewhere.
  `ocr` is untrusted and never runs on the laptop except containerized,
  which is out of scope for the POC and MVP (concept, settled).
- **Isolating the credential from the caller.** In the first cut the
  caller holds the gateway credential and could carry it off. Deferred to
  issue #365 by Todd's ruling.
- **Per-owner credentials.** The first cut shares one service token and one
  1Password service account across both GitHub owners. The seam for the
  split exists (see Credential contract); the split does not.
- **Model management through the gateway.** No pull, delete, create or
  copy. Models are added to the store by hand, using the everyday ollama.
- **A nonprod tier.** There is one laptop and one model store, so a second
  tier would point at the same hardware.
- **Availability guarantees.** The gateway is up when the laptop is up.
  There is no failover, no queueing at the edge, and no retries.
- **Rate limiting or quotas.** ollama's own request queue is the only cap.
  What a credentialed caller can do to availability is stated in Security
  Considerations.
- **A public model API.** Only callers named in tds-internal get a
  credential.

---

## Architecture Overview

```
 caller (e.g. ocr-on-demand on a GitHub runner)
   |  HTTPS to <gateway-host>, with the gateway credential as headers
   v
+----------------------------- Cloudflare ------------------------------+
|  Access application on <gateway-host>     -- checked first: 302/403   |
|    policy: non_identity, includes exactly the named service tokens    |
|  Tunnel (remotely managed): ingress rules declared in tds-internal    |
|    IaC and pushed by Cloudflare to the connector                      |
+-----------------------------------------------------------------------+
   |  outbound-only connection, initiated by the laptop
   v
+------------------------------- laptop --------------------------------+
|  connector daemon (cloudflared, LaunchAgent)                          |
|    applies the pushed ingress rules  -- checked second: 404           |
|      exactly /v1/chat/completions or /v1/models -> 127.0.0.1:<port>   |
|      anything else                    -> 404                          |
|        |  loopback only                                               |
|        v                                                              |
|  +-------------------- macOS sandbox profile -----------------------+ |
|  |  external ollama (LaunchAgent), 127.0.0.1:<port>                 | |
|  |    HOME = gateway config tree                                    | |
|  |    $HOME allow-list: gateway config tree + model store only      | |
|  |    launcher refuses to start unless the probe passes             | |
|  +------------------------------------------------------------------+ |
|                                                                       |
|  everyday ollama, 127.0.0.1:11434 -- unchanged, not on the road       |
|  model store (~/.ollama/models) -- populated only by the everyday     |
|    one; the external one does not modify its contents                 |
+-----------------------------------------------------------------------+

 IaC (tds-internal ops/terraform/ollama-gateway) declares everything in the
 Cloudflare box, plus the ingress rules and the credentials. tds-utils
 lmde/components/ declares everything in the laptop box. Dependencies point
 from the edges to the contract (host, credential headers, paths), never
 from a caller to Cloudflare specifics.
```

---

## Design

### Edge (tds-internal IaC)

The edge is declared in tds-internal `ops/terraform/ollama-gateway/`,
following the `ops/terraform/quillmap-smoketest` service-token pattern. Its
own design record in tds-internal owns the module's internals. This section
states only what the gateway relies on.

#### Responsibilities

| Responsibility | Guarantee the gateway relies on |
|---|---|
| Tunnel | Remotely managed: the ingress rules live in IaC, not in a file on the laptop |
| Ingress allow-list | Exactly two rules route to `http://127.0.0.1:<port>`, each matching one allow-listed path exactly (no prefix or substring match), and a catch-all returns 404 (G3). The rules are declared in IaC and pushed to the connector, which evaluates them on the laptop. `<port>` is an input that must equal the laptop component's value (see Data Model) |
| DNS | `<gateway-host>` routes to the tunnel |
| Access application | Covers all of `<gateway-host>`, with no bypass paths. Evaluated at the edge, before any request reaches the connector |
| Access policy | `decision = non_identity`, including exactly the named service tokens. Never `any_valid_service_token` |
| Service tokens | One per consumer, from a `for_each` map. Dropping a key revokes that consumer |
| Credentials at rest | Each service token's client id and secret, and the tunnel's run token, land in 1Password items, never directly in a GitHub secret |

#### API / Interface

```
POST https://<gateway-host>/v1/chat/completions   (OpenAI-compatible)
GET  https://<gateway-host>/v1/models

Request headers: the gateway credential, as header name/value pairs read
from the consumer's 1Password item (see Credential contract)

Responses, in evaluation order:
  302    missing credential: redirect to the Access login (at the edge)
  403    invalid credential (Access, at the edge)
  5xx    connector not connected (laptop asleep/offline/connector stopped)
  404    any other path (ingress rules, applied by the connector)
  502    connector up, external ollama down
  524    edge proxy time-to-first-byte limit exceeded (e.g. cold load; Q5)
  2xx    the external ollama's response, unmodified
```

### Credential contract

This is what a caller needs to know to use the gateway, plus the seam that
lets owners be split later.

| Item | Value |
|---|---|
| 1Password item title | `ollama-gateway-<consumer>` |
| Contents | The credential as header name/value pairs. Today the names are Cloudflare Access's client-id and client-secret headers. A caller sends whatever headers the item names, and never hardcodes them. The item's field layout is fixed by, and documented in, the tds-internal module's design record |
| Vault | A headless vault, read by a read-only 1Password service account scoped to that vault |
| Consumers in the first cut | One: `gha`, shared by the 9atatimer and Nine-At-A-Time-Media owners |

**The vault is the per-owner seam.**

- A caller resolves the vault from its own configuration, never from a
  constant. In the first cut, every owner's configuration names the same
  vault.
- Splitting an owner off later takes three things: a new `for_each` key, a
  new vault and service account, and a configuration change on that owner.
  It changes neither the gateway nor any caller's code.
- How a caller resolves its vault is the caller's design
  ([OCR on Demand](./OCR-ON-DEMAND.DESIGN.md), to be written).

Because the item carries the header names, the edge-vendor seam holds:
swapping the edge changes the IaC, the connector and the items' contents,
but not callers.

### Connector daemon (tds-utils LMDE)

#### Responsibilities

| Responsibility | Details |
|---|---|
| Hold the tunnel open | Runs `cloudflared` with the tunnel's run token, outbound only |
| Enforce the path allow-list | Applies the ingress rules pushed from IaC, exact-path match (G3). This is the only layer keeping model-management paths off the road in the first cut |
| Transport | Must work on this network. QUIC over IPv6 fails here (observed on an existing cloudflared tunnel on this laptop), so the transport is pinned to `http2` (Key Decisions) |
| Start and restart | A LaunchAgent following the LMDE launchd pattern, restarting on crash |
| Keep the run token out of sight | The token never appears on a process command line, in a LaunchAgent plist, or in a file under the repo. It is read from the laptop's credential store at launch (store: Q2). Whatever the store is, the external ollama's sandbox cannot retrieve it by any means, and the G4 probe asserts that |
| Refuse to run half-configured | No token, no start: the launcher exits non-zero with a message naming what is missing |

The connector is not sandboxed in the first cut. It is a trusted vendor
binary installed by Homebrew, and it must reach the network. See Key
Decisions (connector trust boundary) and Future Considerations.

### External ollama (tds-utils LMDE)

#### Responsibilities

| Responsibility | Details |
|---|---|
| Serve completions | `ollama serve` bound to `127.0.0.1:<port>` only. `<port>` is distinct from the everyday 11434 |
| Run sandboxed | Launched under the gateway's macOS sandbox profile (G4). The profile is a file in the component |
| Refuse to run unconfined | Before every start, the launcher runs the G4 probe under the profile. If confinement is not in effect, the canary is readable, or the run token is retrievable, the launcher exits non-zero with a message and does not start ollama. It never falls back to running unsandboxed |
| Own config tree | `HOME` is the gateway's user config tree under `~/.local/` (the exact path is code), not the user's home. So ollama never touches `~/.ollama/id_ed25519` (its ollama.com identity key) or `~/.ollama/history` |
| Shared store, unmodified | `OLLAMA_MODELS` points at the everyday store, the second allow-listed tree. The external instance does not modify the store's contents; for example, ollama's startup pruning of unreferenced blobs is disabled (load-bearing for G8). Model management cannot reach the store over the road (G3). Enforcing read-only access in the sandbox is part of the hardening pass |
| Bounded memory | Holds at most one model loaded at a time, so the external and everyday instances together cannot load an unbounded set into the laptop's 64 GB |
| Start and restart | A LaunchAgent, same pattern as the connector, with restart on crash |

A spike on 2026-10-02 (issue #363) showed this works. Under such a profile,
ollama 0.34.4:

- found the Metal GPU;
- listed all 23 models read-only;
- served `/v1/chat/completions` at 100% GPU;
- failed to pull (no DNS).

The profile also denied reads of `~/.ssh` and `~/.ollama/id_ed25519`.

**Load-bearing part of the profile.** Inside `$HOME`, the profile is an
allow-list: the gateway's config tree and the model store, nothing else.
That is what keeps credentials out of reach.

**Everything else in the profile.** It may be broad in the first cut, and
its exact text is code. Hardening it (network, store writes, system paths)
is handed to a later pass once the POC runs.

**Confinement-mechanism seam.** The seam is the probe's assertions, not
`sandbox-exec` itself. A successor mechanism needs only to pass the same
probe, and the launcher gates on that probe.

---

## State Machine

These are the gateway's states as a caller sees them, composed from the two
daemons and the edge. The daemons themselves are launchd-managed: started
at login and restarted after a crash. The states below are what a request
meets.

```
                  connector connects, ollama listening
 +-------------+ -----------------------------------> +-------------+
 | UNREACHABLE |                                      |  CONNECTED  |
 +-------------+ <----------------------------------- +-------------+
    ^      |       connector disconnects                 |       ^
    |      |       (sleep, offline, crash)   ollama down |       | ollama up,
    |      |                                             v       | probe passes
    |      |  connector connects,                    +-------------+
    |      |  ollama not listening                   |             |
    |      +---------------------------------------> |  DEGRADED   |
    +----------------------------------------------- |             |
           connector disconnects                     +-------------+
```

| State | Edge answers a credentialed request with | Within |
|---|---|---|
| UNREACHABLE | HTTP 5xx from Cloudflare (tunnel has no connector), whatever the path | 30 s for a stopped connector; sleep/offline unverified (Q6) |
| CONNECTED | HTTP 404 for a non-allow-listed path; otherwise the external ollama's response, or 524 if the first byte exceeds the edge's proxy limit | Model-dependent. A cold load of a ~23 GB model was measured at 1m48s (Q5) |
| DEGRADED | HTTP 404 for a non-allow-listed path; otherwise HTTP 502 from the connector | 5 s |

| From | To | Trigger |
|---|---|---|
| UNREACHABLE | CONNECTED | Connector establishes the tunnel and the external ollama is listening |
| UNREACHABLE | DEGRADED | Connector establishes the tunnel and the external ollama is not listening, including when its launcher refuses to start it |
| CONNECTED | UNREACHABLE | Laptop sleeps, goes offline, or the connector exits |
| CONNECTED | DEGRADED | External ollama exits, stops listening, or is refused start by its launcher |
| DEGRADED | CONNECTED | launchd restarts the external ollama and its probe passes |
| DEGRADED | UNREACHABLE | Connector disconnects |

**A persistently failing probe holds DEGRADED.** If the probe keeps failing
(for example, a macOS update weakens `sandbox-exec`), launchd keeps
relaunching under its own throttling. Each attempt is refused, and the
external ollama never starts unconfined. Recovery needs a human: fix the
profile or plug in a successor mechanism at the probe seam.

**The credential check (G2) applies in every state.** A request without a
valid credential is refused at the edge (302 or 403), whether or not the
laptop is reachable.

**The path check (G3) runs in the connector.** It applies only when the
connector is connected. In UNREACHABLE, a non-allow-listed path gets the
tunnel-down 5xx instead of 404. In every state, such a path never reaches
the external ollama.

---

## Data Model

There is no database. Two declared structures:

```
consumers (tds-internal terraform for_each map)
+-- key                 consumer name, e.g. "gha"; dropping it revokes
+-- -> service token    one per key
+-- -> Access policy    non_identity, includes only that token
+-- -> 1Password item   ollama-gateway-<key>: credential header names
                         and values

laptop component (tds-utils lmde/components/ollama-gateway)
+-- sandbox profile     the external ollama's policy file
+-- probe               the G4 assertions; gates every start
+-- port                external ollama's loopback port (not 11434);
                         single source of truth, mirrored by hand as an
                         input to the tds-internal ingress rules
+-- gateway config tree the external ollama's HOME, under ~/.local/
+-- model store path    the everyday store; the other allow-listed tree
```

A mismatch between the port and the ingress rules' input shows up as
DEGRADED (502). Hand mirroring is the accepted first-cut answer (see
Rejections).

---

## Data Warehouse

Nothing is ledgered. The gateway is a pipe. What flowed through it, and how
often reviews failed, is the caller's to record: OCR on Demand owns review
outcomes and error rates.

One consequence is accepted: with one shared token and no gateway ledger,
misuse cannot be attributed to an owner (Security Considerations).
Per-owner tokens restore attribution (Future Considerations).

---

## Security Considerations

- **Unauthenticated callers.** Refused at the Access edge (G2), before
  anything reaches the laptop. The policy names each token.
  `any_valid_service_token` would admit every service token in the
  account, so it is forbidden.
- **A credentialed caller trying to manage models.** The ingress rules
  route only the two completion paths, by exact match (G3), so
  `/api/pull`, `/api/delete` and the rest never reach the external ollama.
  - Those rules are enforced by the connector on the laptop, not at the
    edge.
  - In the first cut, that is the only layer. Denying store writes in the
    sandbox is part of the hardening pass.
- **A hostile prompt or model exploit in the inference engine.**
  - What the sandbox prevents: the `$HOME` allow-list keeps the user's
    credentials out of reach. That covers `~/.ssh`, AI tool credentials,
    1Password data and ollama's identity key. The run token is
    unretrievable by any means the probe tests (G4).
  - What a compromised engine can still do until the hardening pass
    (accepted risk, by Todd's first-cut ruling):
    - make unrestricted outbound network connections;
    - reach other loopback services, including the everyday ollama on
      11434, which has no auth and exposes model management;
    - read and write paths outside `$HOME`;
    - write the model store.
  - So, before hardening, a compromised engine could alter or delete store
    contents, either directly or through 11434. That is why G8 is scoped
    to normal operation. It could not read what is worth stealing in the
    home directory. Whether loopback and store denial move into the first
    cut is Q7.
- **Availability abuse by a token holder.** Anyone holding the shared
  token can saturate the gateway with concurrent or very large requests.
  - The only caps are ollama's own request queue (excess requests are
    rejected, not held) and the one-loaded-model bound.
  - The laptop's everyday work can be slowed, but no data is exposed.
  - Accepted, per the Non-Goals. The response is revocation.
- **Tool calls.** ollama is an inference server with no tool-execution
  capability: it returns a model's tool calls to the caller as data.
  - On the laptop, the gateway does not rely on that: whatever the engine
    does runs inside the sandbox (G4).
  - What a caller does with returned tool calls, including treating them
    as untrusted output, is the caller's design (OCR on Demand).
- **Credential theft by the caller.** In the first cut the caller holds the
  gateway credential and could exfiltrate it.
  - Whoever holds it can then get completions, but no more: G3 and G4
    still hold.
  - One shared token means one leak exposes the road for both owners.
  - One owner's compromised CI can act as the other owner's caller, and
    nothing distinguishes them. The edge sees one token and the gateway
    records nothing, so misuse cannot be attributed to an owner.
  - Revocation is dropping the consumer key and re-applying. That cuts off
    both owners at once.
  - Accepted for the first cut; issue #365 tracks isolation, and per-owner
    tokens (Future Considerations) restore attribution.
- **The tunnel run token.** Whoever holds it can impersonate the laptop's
  connector.
  - It lives in 1Password (IaC) and in the laptop's credential store
    (Q2), never on a command line, in the repo, or in a LaunchAgent plist.
  - Whichever store Q2 picks, it must be unretrievable from inside the
    external ollama's sandbox, and the G4 probe must assert that.
  - A mode-600 file under `$HOME` but outside the allow-list is covered by
    the path denial and the canary check.
  - A Keychain item is not read by path. It is reached through the
    Security framework or `/usr/bin/security`, which the broad first-cut
    profile may admit. It qualifies only if the probe's retrieval attempts
    by those means fail under the profile.
- **Prompt and completion contents.** They cross Cloudflare's edge, with
  TLS terminated there. This is acceptable for code under review in the
  fleet's own repos. No other data is intended to use the road.
- **Crossing the LMDE "never routable" non-goal.** This is the one
  deliberate public ingress. It is bounded by G2, G3 and G4. It is recorded
  as a Key Decision here and as an appended Key Decisions row in
  `LMDE.DESIGN.md`.
- **sandbox-exec is deprecated by Apple** but works on this macOS. If a
  macOS update removes or weakens it, the probe fails and the launcher
  refuses to start the external ollama. The gateway stays DEGRADED rather
  than unconfined (State Machine). See the radar row.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the gateway lives | An LMDE sub-component, separate from any caller | Todd (concept, settled): a further evolution of our use of ollama, its own domain |
| Who declares cloud resources and credentials | tds-internal terraform, all of them | Todd (concept, settled): all IaC and all credentials live in tds-internal |
| Who runs the laptop daemons | tds-utils LMDE, launchd pattern | Todd (concept, settled) |
| Which ollama is on the road | A second, external-facing instance, never the everyday one | Todd (concept, settled): the external ollama is a security domain; the everyday one keeps its identity key, history and network |
| How the external ollama is confined | The basic macOS sandbox (`sandbox-exec` profile) | Todd (concept, settled): start with the basic Mac sandbox. Spike 2026-10-02 shows GPU inference works under it; Docker on macOS has no Metal GPU |
| Confinement-mechanism axis | Seam = the G4 probe's assertions, which gate every start; no fallback to running unconfined | `sandbox-exec` is deprecated and will change; a successor only has to pass the same probe |
| Sandbox policy scope, first cut | Load-bearing: `$HOME` is an allow-list (the gateway's user config tree under `~/.local/`, plus the model store), and the run token is unretrievable. Everything else may be broad | Todd (2026-10-02): protect `~/.ssh`, AI creds and such with a whitelist of a user config tree; get it running in any sandbox first, and hand hardening to a smarter model after the POC works |
| Connector trust boundary | Unsandboxed in the first cut; trusted as a signed vendor binary. The confinement boundary is drawn around the inference engine, which processes untrusted input, not around everything on the road | The connector parses only tunnel protocol and needs the network; the engine runs hostile prompts and models |
| Model files | Shared everyday store, the external instance's second allow-listed tree; the external instance does not modify its contents | No second copy of tens of GB. G3 keeps model management off the road, G8 forbids local modification in normal operation, and the hardening pass makes the store read-only |
| Tunnel config | Remotely managed, ingress in IaC | The path allow-list is a security control (G3) and belongs in reviewed IaC, not a laptop file |
| Path exposure | Allow-list by exact match: `/v1/chat/completions`, `/v1/models`; 404 otherwise, enforced by the connector after Access | ollama has no auth and exposes model-management endpoints; a prefix or substring match would widen the allow-list silently |
| Access policy | `non_identity`, naming each token | Revocable per consumer; `any_valid_service_token` admits every token in the account |
| Credentials for the first cut | One service token, one 1Password service account, shared by both GitHub owners | Todd's ruling (PR #364) |
| Per-owner axis of change | Seam = the vault a caller resolves from its own configuration; tokens are a `for_each` map | Splitting owners later needs no gateway or caller code change |
| Caller isolation from the credential | Not in the first cut | Todd's ruling on codex review, PR #364; issue #365 |
| Transport | `http2` | QUIC over IPv6 fails on this network |
| Edge vendor axis | Seam = the caller contract (URL + paths + credential header names and values read from the 1Password item) | Callers never hardcode Cloudflare header names. Swapping the edge changes the IaC, the connector and the items' contents only |
| Model choice | Not the gateway's: callers name a model; the gateway serves the store | The model is a caller detail (concept: "whatever gets it done") |
| Radar: cloudflared | Propose Trial, in `lmde/TECH_RADAR.md` and tds-internal `docs/TECH_RADAR.md` | Todd (concept, settled). Exit: the gateway runs a month without a manual restart |
| Radar: macOS sandbox (`sandbox-exec`) | Propose Trial in `lmde/TECH_RADAR.md` | Apple-deprecated API; Trial until a supported replacement is chosen or it proves stable across a macOS major update |
| LMDE "Public ingress" non-goal | Crossed for this one endpoint; append a Key Decisions row to `LMDE.DESIGN.md` citing this record and issue #363 | The LMDE record is frozen; its log is append-only |

---

## Open Questions

- **Q1 Hostname and tier.** *Blocks the IaC.* `<gateway-host>` is named
  in the tds-internal record, not here: this repo is public, and the
  concrete hostname, zone and account belong with the IaC.
  - Proposed there: production tier only, bare `<service>.<zone>` per the
    naming rule (see the "A nonprod tier" Non-Goal).
  - tds-internal's convention is that a request naming no tier means
    nonprod, so a production-only module is an explicit exception there.
  - Needs Todd's confirmation.
- **Q2 Where the connector's run token lives on the laptop.** *Blocks
  APPROVED.* The daemon must start while 1Password is locked (G7), and the
  token must be unretrievable from the external ollama's sandbox, as
  asserted by the G4 probe.
  - Option A: cloudflared's own credentials file, mode 600, under a
    private directory outside the sandbox's `$HOME` allow-list. The path
    denial and canary check cover it as specified.
  - Option B: the macOS login Keychain, seeded once from the 1Password
    item by a setup step and read at launch. It is reachable through the
    Security framework and `/usr/bin/security`, not by path. It qualifies
    only if the probe shows those routes fail under the first-cut profile,
    which is not yet established.
- **Q3 Memory contention.** Two ollama servers on one 64 GB laptop can each
  hold a large model.
  - Bounding the external instance to one loaded model (Design) caps it,
    but the everyday instance is unbounded.
  - Is that enough, or should the external one also unload promptly after
    each review?
- **Q4 The name.** "Ollama Gateway" is the working name from the concept.
  Confirm it or choose another.
- **Q5 Cold loads vs. the edge's proxy timeout.** *Blocks APPROVED; G1
  depends on it.*
  - Cloudflare's proxied requests are believed to carry a ~100 s
    time-to-first-byte limit on non-Enterprise plans, after which the edge
    returns 524. This needs verifying.
  - A measured 1m48s cold load would exceed it, as could a long
    non-streamed completion.
  - Candidate guarantees:
    - (a) callers stream, and the external instance keeps the model
      resident, or pre-warms it, so first byte is prompt;
    - (b) G1 is scoped to warm models, and callers treat 524 as retryable;
    - (c) both.
  - The chosen option is recorded as a Key Decisions row, and G1 is
    amended to match.
- **Q6 Detection of a silent connector.** G5's 30 s bound is stated for a
  stopped connector. For a sleeping or offline laptop, the bound depends
  on Cloudflare's dead-connector detection. Verify it, then fix the bound
  or document the measured one.
- **Q7 Loopback and store denial in the first cut.** Without them, a
  compromised engine can reach 11434 and alter the store (Security
  Considerations), so G8 holds only in normal operation.
  - The spike suggests network denial does not break inference, so
    pulling these into the first cut may be cheap. If pulled forward, G8's
    compromise caveat is removed.
  - Todd's ruling defers all hardening.
  - Needs Todd's decision.

---

## Rejections

- **Expose the everyday ollama on 11434 directly.** It holds ollama's
  identity key and history, has network, and can manage models. The
  concept requires a separate, sandboxed external instance.
- **Run the external ollama in Docker.** Docker on macOS has no Metal GPU,
  so inference would fall back to CPU.
- **Locally managed tunnel config (`~/.cloudflared/config.yml`).** It
  would put the path allow-list, a security control, in an unreviewed
  laptop file.
- **Reuse the existing cloudflared tunnel on this laptop.** It belongs to
  another Cloudflare account and another system. A new system gets its own
  credentials, never a borrowed one (tds-internal policy).
- **`any_valid_service_token` in the Access policy.** It admits every
  service token in the account, and cannot revoke one consumer.
- **Expose all ollama paths and rely on the sandbox alone.** In the first
  cut the sandbox does not deny store writes or network, so the path
  allow-list is what keeps model management off the road. After hardening,
  it stays as a second layer.
- **Start the external ollama unconfined if the sandbox probe fails.** A
  DEGRADED gateway is acceptable; an unconfined one is not.
- **Per-owner service tokens and service accounts in the first cut.**
  Todd's ruling: POC with one; the vault seam keeps the split cheap later.
- **Hardcode Cloudflare credential header names in callers.** It would
  break the edge-vendor seam. The 1Password item carries them instead.
- **IP- or ASN-restricting the Access policy.** GitHub-hosted runners have
  ephemeral, broad IP ranges, so the restriction would bound nothing
  useful.
- **A GitHub App for the caller's Cloudflare credential.** It solves
  GitHub-side identity, not Cloudflare's.
- **An SSH reverse tunnel or Tailscale Funnel instead of cloudflared.**
  Todd settled on cloudflared and Access, and tds-internal already has the
  Access service-token pattern and its IaC.
- **A nonprod tier.** One laptop, one store: it would test nothing the
  production tier does not.
- **Sandboxing the connector in the first cut.** It needs the network, is
  a signed vendor binary, and sees only what the tunnel routes.
- **Cross-repo wiring to derive the ingress port from the laptop
  component.** One rarely changing value across two repos; the wiring
  would be a single-implementation seam. A mismatch is visible as
  DEGRADED (502).

---

## Future Considerations

- **Sandbox hardening pass.** After the POC runs, a stronger model reviews
  and tightens the profile:
  - outbound network denied;
  - loopback limited to what inference needs, with no reach to other
    loopback services such as 11434;
  - model store read-only;
  - system paths narrowed.

  The 2026-10-02 spike showed the network and home denials do not break
  GPU inference. Q7 may pull part of this forward. Completing it lifts
  G8's compromise caveat.
- **Credential isolation from the caller.** Issue #365.
- **Per-owner credentials.** One consumer key, vault and service account
  per GitHub owner, once the first cut has proven the road. This also
  restores per-owner attribution and revocation.
- **Sandboxing the connector**, limiting it to its config and loopback.
- **Gateway metrics in the LMDE observability stack.** Connector state and
  request counts, if review error rates point at the gateway.
- **A supported successor to sandbox-exec**, should Apple remove it. It
  plugs in at the probe seam.
- **More callers.** Each is a new consumer key; the contract does not
  change.

---

## Related Documents

- [LMDE](./LMDE.DESIGN.md): the platform this is a sub-component of. Its
  "Public ingress" non-goal is crossed here for one endpoint.
- tds-internal `ops/terraform/ollama-gateway` design record (not yet
  written; written alongside this one): owns the edge module and the
  1Password item's field layout. Callers such as OCR on Demand cannot be
  built from the Credential contract until it exists.
- [concept: ollama-gateway](../concepts/ollama-gateway/CONCEPT.md): origin
  (non-binding).
- [concept: ocr-on-demand](../concepts/ocr-on-demand/CONCEPT.md): the
  first caller's concept.
- OCR on Demand (`OCR-ON-DEMAND.DESIGN.md`, to be written): the first
  caller. It owns vault resolution, handling of returned tool calls, and
  review outcomes.
- tds-internal `ops/terraform/quillmap-smoketest`: the service-token
  pattern the edge follows.
- tds-internal `docs/policy/CREDENTIALS.md`, `INFRASTRUCTURE.md`,
  `TERRAFORM.md`: the rules the edge obeys.
- [REMOLLAMA](./REMOLLAMA.DESIGN.md): the opposite direction (laptop
  reaching a rented GPU). Unrelated mechanism.