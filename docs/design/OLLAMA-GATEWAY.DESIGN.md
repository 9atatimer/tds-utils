# Ollama Gateway

> **Status:** REVIEW  
> **Date:** 2026-10-02  
> **Authors:** Todd Stumpf, Claude (Opus 5.5)  
> **Depends on:** [LMDE](./LMDE.DESIGN.md); the tds-internal edge record `DESIGN.ollama-gateway-infra.md` (tds-internal PR #125), which owns `ops/terraform/ollama-gateway` and the 1Password item the connector's Keychain copy of the run token is seeded from  
> **Origin:** [concept: ollama-gateway](../concepts/ollama-gateway/CONCEPT.md), issue #363

---

## Overview

The Ollama Gateway is an LMDE sub-component that lets an authorized caller
off the laptop get completions from a model on the laptop. The first caller
is a GitHub Actions run of Open Code Review. The gateway is a Cloudflare
Access-protected cloudflared tunnel, then the deadline proxy -- the
gateway's route on the LMDE proxy layer, the one local front door that
every laptop service with a public port sits behind -- in front
of a second, external-facing ollama. That ollama runs inside the macOS sandbox, so nothing arriving over
the tunnel can read the user's credentials: `~/.ssh`, AI tool credentials,
or anything else in the home directory outside an allow-listed tree.

---

## Goals

- **G1 Authorized completions.** A caller presenting a valid gateway
  credential to `https://<gateway-host>/v1/chat/completions` gets a
  completion from a model in the laptop's store, and `GET /v1/models` lists
  those models. A request the external ollama cannot start answering in
  time -- typically the first one after a cold model load, measured at
  1m48s for a ~23 GB model -- does not hang and does not time out at the
  edge: the deadline proxy answers it before the edge's time-to-first-byte
  limit with the deadline answer, the one response a caller retries
  (Deadline proxy).
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
  - The connector's run token (in the Keychain) is unreachable from inside the sandbox
    by any means, not only by path.
  - Both properties are asserted by a probe that runs under the profile.
    They are not inferred from the profile text. The probe's acceptance
    criteria are:
    - a canary file under `$HOME`, outside both allow-listed trees, is
      unreadable;
    - every means the connector's launcher uses to retrieve the run token,
      including the Security framework and `/usr/bin/security`, fails.
  - Outside `$HOME`, the first-cut sandbox may be broad. Security
    Considerations names what that admits. Tightening it is a later
    hardening pass (Future Considerations).
- **G5 Outages fail fast.** No outage makes a request hang.
  - With the connector stopped, the Cloudflare edge answers a request with
    HTTP 5xx within 30 seconds.
  - With the laptop asleep or offline, the bound depends on how fast the
    edge detects a silent connector. That bound is unverified (Q6).
  - With the connector up but the external ollama down, the deadline proxy
    answers HTTP 5xx within 5 seconds; with the proxy down, the connector
    answers HTTP 502 within 5 seconds.
- **G6 Everything is IaC.** Every Cloudflare resource and every credential
  on the road is declared in tds-internal terraform. That means the tunnel,
  DNS, the Access application and policy, the service tokens, and the
  1Password items holding them.
  - There is one exception: the 1Password service account, which terraform
    cannot create (tds-internal `docs/policy/CREDENTIALS.md`).
  - The laptop's local copy of the run token is seeded from its 1Password
    item. It is not a separately minted credential.
- **G7 Runs unattended.** The three laptop daemons (connector, deadline
  proxy, external ollama) start at login and restart after a crash. None
  needs a human, and none needs 1Password to be unlocked. A failing G4
  probe is not a crash: the launcher refuses to start the external ollama,
  and the gateway stays DEGRADED until the probe passes. For a persistent
  cause, that needs a human (State Machine).
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
  tier would point at the same hardware. Settled here; only the hostname
  is open (Q1).
- **Availability guarantees.** The gateway is up when the laptop is up.
  There is no failover, no queueing at the edge, and no retries at the
  edge or gateway; retrying the deadline answer is the caller's.
- **Rate limiting or quotas.** ollama's own request queue is the only cap
  in the PoC unless Q12 sets first-cut limits on the LMDE proxy layer,
  which is where any limit lives; finer request shaping is v2 (Future
  Considerations).
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
|      exactly /v1/chat/completions or /v1/models                       |
|                                         -> 127.0.0.1:<proxy-port>     |
|      anything else                    -> 404                          |
|        |  loopback only                                               |
|        v                                                              |
|  LMDE proxy layer (LaunchAgent): deadline proxy route,                |
|    127.0.0.1:<proxy-port>; shared throttling and payload limits       |
|    first byte from ollama before the deadline, or an HTTP 5xx         |
|        |  loopback only                                               |
|        v                                                              |
|  +-------------------- macOS sandbox profile -----------------------+ |
|  |  external ollama (LaunchAgent), 127.0.0.1:<ollama-port>          | |
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
 from the edges to the contract (host, credential headers, paths, retryable
 status), never from a caller to Cloudflare specifics.
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
| Ingress allow-list | Exactly two rules route to `http://127.0.0.1:<proxy-port>`, each matching one allow-listed path exactly (no prefix or substring match), and a catch-all returns 404 (G3). The rules are declared in IaC and pushed to the connector, which evaluates them on the laptop. `<proxy-port>` is an input that must equal the laptop component's value (see Data Model; drift is Q8) |
| DNS | `<gateway-host>` routes to the tunnel |
| Access application | Covers all of `<gateway-host>`, with no bypass paths. Evaluated at the edge, before any request reaches the connector |
| Access policy | `decision = non_identity`, including exactly the named service tokens. Never `any_valid_service_token` |
| Service tokens | One per consumer, from a `for_each` map. Dropping a key revokes that consumer |
| Credentials at rest | Each service token's client id and secret, and the tunnel's run token, land in 1Password items, never directly in a GitHub secret. The run token's item is in a vault no caller's service account can read, so a caller's credentials never yield the run token (Security Considerations) |

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
  502    connector up, deadline proxy down
  5xx    deadline proxy: external ollama down
  5xx    deadline proxy: the deadline answer -- no first byte before the
         deadline (e.g. cold load). The only retryable response
  2xx    the external ollama's response, unmodified
```

### Credential contract

This is what a caller needs to know to use the gateway, plus the seam that
lets owners be split later.

| Item | Value |
|---|---|
| 1Password item | One per consumer; its title is named in the tds-internal record (this repo is public) |
| Contents | The credential as header name/value pairs. Today the names are Cloudflare Access's client-id and client-secret headers. A caller sends whatever headers the item names, and never hardcodes them. The item's field layout is fixed by, and documented in, the tds-internal module's design record |
| Vault | A headless vault, read by a read-only 1Password service account scoped to that vault |
| Service-account credential | Where a caller holds the service account's own token, and how it authenticates to 1Password, is the caller's design (OCR on Demand) |
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

**Retryable status.** A caller can identify the deadline answer from the
status code alone, distinct from every other 5xx in the API listing,
including the edge's and the connector's. It is the only response the
gateway designates retryable; every other failure is terminal for that
request. The code is chosen in the deadline proxy, verified distinct as a
behavior, and is part of the caller contract.

### Connector daemon (tds-utils LMDE)

#### Responsibilities

| Responsibility | Details |
|---|---|
| Hold the tunnel open | Runs `cloudflared` with the tunnel's run token, outbound only |
| Enforce the path allow-list | Applies the ingress rules pushed from IaC, exact-path match (G3). This is the only layer keeping model-management paths off the road in the first cut |
| Transport | Must work on this network. QUIC over IPv6 fails here (observed on an existing cloudflared tunnel on this laptop), so the transport is pinned to `http2` (Key Decisions) |
| Start and restart | A LaunchAgent following the LMDE launchd pattern, restarting on crash |
| Keep the run token out of sight | The token never appears on a process command line, in a LaunchAgent plist, or in a file under the repo. It is read from the macOS login Keychain at launch, seeded once from its 1Password item by a setup step (Key Decisions; what authenticates that step is Q9). The external ollama's sandbox cannot retrieve it by any means, and the G4 probe asserts that, including through the Security framework and `/usr/bin/security` |
| Refuse to run half-configured | No token, no start: the launcher exits non-zero with a message naming what is missing |

The connector is not sandboxed in the first cut. It is a trusted vendor
binary installed by Homebrew, and it must reach the network. See Key
Decisions (connector trust boundary) and Future Considerations.

### Deadline proxy (the gateway's route on the LMDE proxy layer)

**The LMDE proxy layer** is one local reverse proxy, part of the LMDE
ecosystem, that every laptop service needing a public port sits behind
and plays nice with. It centralizes throttling, maximum payload sizes and
the like, so no service grows its own (Todd, 2026-10-02). The gateway is
its first tenant; the second is the chores webhook endpoint (concept:
chores-webhooks, PR #379), which has its own tunnel. Each tenant is a
route on the layer with its own limits; this record specifies only the
gateway's route.

**The deadline proxy** is that route: the layer's configuration between
the connector and the external ollama. It exists so that a request the
external ollama cannot start answering in time never reaches the edge's
time-to-first-byte limit (Todd, 2026-10-02: "an nginx/haproxy that ensures
it always returns something, even if it's a 500").

#### Responsibilities

| Responsibility | Details |
|---|---|
| Always answer in time | For every request, returns either the external ollama's response (streamed through as it arrives) or an HTTP 5xx, and its first byte leaves before a deadline set below the edge's time-to-first-byte limit. The limit is believed to be ~100 s on this plan; it is verified, and the deadline set under it, as a behavior |
| Say why | The deadline answer ("no first byte before the deadline") is distinguishable by status code alone from "ollama not listening" and from every other 5xx a caller can see (Credential contract, Retryable status) |
| Let the load finish | A deadline answer must not cancel the model load in progress, so the caller's retry finds the model warm. That ollama completes a load after the requesting connection closes is verified as a behavior; if it does not, the proxy holds the upstream request open past the deadline while answering the caller |
| Loopback only | Listens on `127.0.0.1:<proxy-port>`, forwards to `127.0.0.1:<ollama-port>`, nothing else |
| Start and restart | A LaunchAgent, LMDE pattern, restart on crash |
| Limits live on the layer | Throttling and maximum payload size for the gateway's route are set on the LMDE proxy layer, beside every other tenant's, never in the external ollama or the connector. The first-cut values, and whether the first cut sets any, are Q12 |
| Tenants stay apart | The gateway route's limits, deadline and upstream apply to the gateway's traffic only; another tenant's route never reaches `<ollama-port>`. How the layer tells routes apart is Q12 |

Which proxy the layer runs is an implementation choice: Todd named nginx
or haproxy; the LMDE's Caddy (already Adopt on `lmde/TECH_RADAR.md`) also
qualifies and would avoid a new radar row. The choice is made once, for
the layer, not per tenant. The proxy is a trusted Homebrew binary on
loopback and is not sandboxed in the first cut.

### External ollama (tds-utils LMDE)

#### Responsibilities

| Responsibility | Details |
|---|---|
| Serve completions | `ollama serve` bound to `127.0.0.1:<ollama-port>` only, distinct from the everyday 11434. Its only client is the deadline proxy |
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

These are the gateway's states as a caller sees them, composed from the three
laptop daemons and the edge. The daemons themselves are launchd-managed: started
at login and restarted after a crash. The states below are what a request
meets.

| State | Condition |
|---|---|
| UNREACHABLE | Connector not connected |
| CONNECTED | Connector connected, deadline proxy listening, and external ollama listening |
| DEGRADED | Connector connected, and the deadline proxy or the external ollama (or both) not listening |

```
                 connector connects, proxy and ollama listening
 +-------------+ -----------------------------------> +-------------+
 | UNREACHABLE |                                      |  CONNECTED  |
 +-------------+ <----------------------------------- +-------------+
    ^      |       connector disconnects                 |       ^
    |      |       (sleep, offline, crash)      proxy or |       | proxy and ollama
    |      |                                 ollama down |       | up (ollama only
    |      |                                             v       | after probe passes)
    |      |  connector connects,                    +-------------+
    |      |  proxy or ollama not listening          |             |
    |      +---------------------------------------> |  DEGRADED   |
    +----------------------------------------------- |             |
           connector disconnects                     +-------------+
```

| State | Edge answers a credentialed request with | Within |
|---|---|---|
| UNREACHABLE | HTTP 5xx from Cloudflare (tunnel has no connector), whatever the path | 30 s for a stopped connector; sleep/offline unverified (Q6) |
| CONNECTED | HTTP 404 for a non-allow-listed path; otherwise the external ollama's response, or the deadline answer (retryable) when no first byte arrives before the deadline (e.g. a cold load) | First byte always before the edge's limit |
| DEGRADED | HTTP 404 for a non-allow-listed path; otherwise HTTP 5xx from the deadline proxy (ollama down) or 502 from the connector (proxy down) | 5 s |

| From | To | Trigger |
|---|---|---|
| UNREACHABLE | CONNECTED | Connector establishes the tunnel, and the deadline proxy and external ollama are both listening |
| UNREACHABLE | DEGRADED | Connector establishes the tunnel, and the deadline proxy or external ollama is not listening, including when the ollama launcher refuses to start it |
| CONNECTED | UNREACHABLE | Laptop sleeps, goes offline, or the connector exits |
| CONNECTED | DEGRADED | Deadline proxy or external ollama exits or stops listening, or the ollama launcher refuses a start |
| DEGRADED | CONNECTED | launchd has restarted whichever daemon was down, so both are listening; the external ollama listens only after its probe passes |
| DEGRADED | UNREACHABLE | Connector disconnects |

**A failing probe holds DEGRADED until it passes.** The launcher exits
non-zero, launchd relaunches under its own throttling, and each attempt
reruns the probe. The external ollama never starts unconfined. A transient
cause clears on its own; a persistent one (for example, a macOS update
weakens `sandbox-exec`) needs a human to fix the profile or plug in a
successor mechanism at the probe seam.

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
+-- -> 1Password item   one per key (title in tds-internal): credential header names
                         and values

laptop component (tds-utils lmde/components/ollama-gateway)
+-- sandbox profile     the external ollama's policy file
+-- probe               the G4 assertions; gates every start
+-- proxy-port          deadline proxy's loopback port; single source of
                         truth, mirrored by hand as an input to the
                         tds-internal ingress rules
+-- ollama-port         external ollama's loopback port (not 11434);
                         read only by the deadline proxy
+-- gateway config tree the external ollama's HOME, under ~/.local/
+-- model store path    the everyday store; the other allow-listed tree
```

A mismatch between `proxy-port` and the ingress rules' input shows up as
DEGRADED (502) only when nothing listens on the port the edge names; if
something does, requests reach it instead (Security Considerations, Q8).
Hand mirroring is the first-cut answer (see Rejections).

---

## Data Warehouse

Nothing is ledgered. The gateway is a pipe. What flowed through it, and how
often reviews failed, is the caller's to record: OCR on Demand owns review
outcomes and error rates.

One consequence is accepted: with one shared token and no gateway ledger,
misuse cannot be attributed to an owner (Security Considerations).
Per-owner tokens restore attribution (Future Considerations).

Whether the connector or deadline proxy write request or response bodies
to local logs is open (Q10).

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
  - The same holds for the caller's 1Password service-account token: it
    reads only the consumer vault, never the run token's item (Edge,
    Credentials at rest). Where the caller keeps that token is the
    caller's design.
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
  - It lives in 1Password (IaC) and in the macOS login Keychain (Todd's
    choice), never on a command line, in the repo, or in a LaunchAgent
    plist.
  - What authenticates the one-time seeding step to 1Password, and that
    nothing of it persists afterward, is Q9.
  - A Keychain item is not read by path. It is reached through the
    Security framework or `/usr/bin/security`, which the broad first-cut
    profile may admit. So the G4 probe attempts retrieval by those means
    under the profile, and the profile must deny them -- that one denial is
    part of the first cut, not the hardening pass. If it cannot be denied,
    the launcher refuses to start the external ollama (DEGRADED).
- **The origin port is a trust boundary.** The edge routes allow-listed
  requests to `127.0.0.1:<proxy-port>`, mirrored by hand in the tds-internal
  module. The laptop component owns keeping `<proxy-port>` bound by the
  deadline proxy, and `<ollama-port>` by the external ollama, and nothing
  else. That does not cover drift: if the edge's value drifts, it names a
  port the laptop component does not own.
  - With nothing listening there, drift shows as DEGRADED (502).
  - If another local service listens there, credentialed allow-listed
    requests reach that service, bypassing the deadline proxy and the
    sandbox (G4).
  - Whether drift is detected, or accepted as a first-cut risk, is Q8.
- **Prompt and completion contents.** They cross Cloudflare's edge, with
  TLS terminated there. This is acceptable for code under review in the
  fleet's own repos. No other data is intended to use the road. Local
  logging of contents is Q10.
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
| Connector run token on the laptop | The macOS login Keychain, seeded once from 1Password; the sandbox profile denies retrieval through the Security framework and `/usr/bin/security`, and the G4 probe asserts it. Its 1Password item is in a vault no caller's service account reads | Todd, 2026-10-02 (was Q2). Vault separation keeps a caller's credentials from yielding the run token |
| Cold loads vs. the edge's time-to-first-byte limit | A local deadline proxy that always answers before the limit, with a retryable deadline answer if ollama has not started answering; callers retry | Todd, 2026-10-02 (was Q5): "an nginx/haproxy that ensures it always returns something, even if it's a 500". Keeping the model resident would hold ~23 GB of RAM permanently |
| Which failures a caller retries | Only the deadline answer, identifiable by status code alone; every other failure is terminal for that request | A caller must tell warming from outage without guessing; retrying every 5xx would mask outages |
| Edge vendor axis | Seam = the caller contract (URL + paths + credential header names and values read from the 1Password item + retryable status) | Callers never hardcode Cloudflare header names. Swapping the edge changes the IaC, the connector and the items' contents only. The seam does not cover G3's enforcement point: a replacement edge must provide its own exact-path enforcement before the external ollama, and G3 is the guarantee it must meet |
| Model choice | Not the gateway's: callers name a model; the gateway serves the store | The model is a caller detail (concept: "whatever gets it done") |
| Radar: cloudflared | Propose Trial, in `lmde/TECH_RADAR.md` and tds-internal `docs/TECH_RADAR.md` | Todd (concept, settled). Exit: the gateway runs a month without a manual restart |
| Radar: deadline proxy | Caddy if it meets the deadline requirement (already Adopt in `lmde/TECH_RADAR.md`); otherwise propose nginx or haproxy at Trial with the code | No new dependency when an adopted one suffices |
| Where the deadline proxy lives | A route on the LMDE proxy layer: one local reverse proxy that every laptop service with a public port sits behind, centralizing throttling and maximum payload sizes | Todd, 2026-10-02 (chores-webhooks concept, PR #379): "We'd want that proxy layer to be part of the lmde ecosystem, and anything local that needs a public port should play nice with it." |
| Radar: macOS sandbox (`sandbox-exec`) | Propose Trial in `lmde/TECH_RADAR.md` | Apple-deprecated API; Trial until a supported replacement is chosen or it proves stable across a macOS major update |
| LMDE "Public ingress" non-goal | Crossed for this one endpoint; append a Key Decisions row to `LMDE.DESIGN.md` citing this record and issue #363 | The LMDE record is frozen; its log is append-only |

---

## Open Questions

- **Q1 Hostname.** *Blocks the IaC.* The tier scope is settled here
  (production only; see Non-Goals). What remains is naming:
  `<gateway-host>` is named in the tds-internal record, not here, because
  this repo is public and the concrete hostname, zone and account belong
  with the IaC.
  - Proposed there: bare `<service>.<zone>` per the naming rule.
  - tds-internal's convention is that a request naming no tier means
    nonprod, so a production-only module is an explicit exception there.
  - Needs Todd's confirmation.
- **Q3 Memory contention.** Two ollama servers on one 64 GB laptop can each
  hold a large model.
  - Bounding the external instance to one loaded model (Design) caps it,
    but the everyday instance is unbounded.
  - Is that enough, or should the external one also unload promptly after
    each review?
- **Q4 The name.** "Ollama Gateway" is the working name from the concept.
  Confirm it or choose another.
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
- **Q8 Origin-port drift.** If the hand-mirrored ingress port drifts and
  another local service listens on it, allow-listed requests bypass the
  sandbox (Security Considerations). Two answers:
  - (a) add a guarantee that drift is detected -- an allow-listed request
    through the tunnel is verified to reach the deadline proxy -- leaving
    the mechanism to code;
  - (b) accept it as a named first-cut risk alongside the others.
  - Needs Todd's decision. The Rejections row for cross-repo port wiring
    stands or falls with it.
- **Q9 Authenticating the run-token seeding step.** Settled by the
  tds-internal record: the run token's item sits in a vault no service
  account can read, so seeding is an interactive human session (the `op`
  CLI unlocked through the desktop app), and no 1Password credential
  persists on the laptop afterward. Todd to confirm.
- **Q10 Local logging of contents.** Whether the connector or deadline
  proxy write request or response bodies (code under review) to disk, and
  if so their home and retention, is not yet stated. The likely answer is
  that neither logs bodies.
- **Q12 The gateway's route on the LMDE proxy layer.** Two things are not
  yet stated:
  - the gateway route's first-cut throttling and maximum payload size, or
    that the first cut sets none;
  - how the layer tells tenants apart now that each has its own tunnel: a
    loopback listener per route keeps each tunnel's `origin_port`
    one-to-one with a route (and Q8's drift reasoning per port), while one
    listener routing by hostname shares a port across tenants.

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
- **A gateway-only proxy.** Every laptop service with a public port would
  grow its own throttling and size limits. Todd, 2026-10-02: one LMDE
  proxy layer that anything local needing a public port plays nice with.
- **Cross-repo wiring to derive the ingress port from the laptop
  component.** One rarely changing value across two repos; the wiring
  would be a single-implementation seam. This rejection does not by itself
  cover drift onto a port another service listens on; that is Q8.

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
- **Request shaping in front of the external ollama (v2).** On the LMDE
  proxy layer's gateway route (or a Cloudflare Worker in front of the
  tunnel): finer control of request rates and query sizes than Q12's
  first-cut limits, and rewriting the public paths to something other than
  ollama's own. Not for the PoC; it is the planned answer to availability
  abuse, and the place a PoC hurdle in this area gets deferred to (Todd,
  PR #369).
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
- tds-internal `DESIGN.ollama-gateway-infra.md` (tds-internal PR #125):
  owns the edge module and the 1Password items' field layout. Callers such as OCR on Demand cannot be
  built from the Credential contract until it exists, and neither can this
  component's run-token seeding step, which reads an item whose layout that
  record fixes.
- [concept: ollama-gateway](../concepts/ollama-gateway/CONCEPT.md): origin
  (non-binding).
- [concept: ocr-on-demand](../concepts/ocr-on-demand/CONCEPT.md): the
  first caller's concept.
- concept: chores-webhooks (PR #379): the LMDE proxy layer's second
  tenant, a chores webhook endpoint on its own tunnel.
- OCR on Demand (`OCR-ON-DEMAND.DESIGN.md`, to be written): the first
  caller. It owns vault resolution, its service-account credential, retry
  of the deadline answer, handling of returned tool calls, and review
  outcomes.
- tds-internal `ops/terraform/quillmap-smoketest`: the service-token
  pattern the edge follows.
- tds-internal `docs/policy/CREDENTIALS.md`, `INFRASTRUCTURE.md`,
  `TERRAFORM.md`: the rules the edge obeys.
- [REMOLLAMA](./REMOLLAMA.DESIGN.md): the opposite direction (laptop
  reaching a rented GPU). Unrelated mechanism.
