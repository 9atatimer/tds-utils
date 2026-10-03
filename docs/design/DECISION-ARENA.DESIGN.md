# Decision Arena

> **Status:** DRAFT  
> **Date:** 2026-10-03  
> **Authors:** Todd Stumpf, Claude (Opus 5.5)  
> **Depends on:** [LMDE](./LMDE.DESIGN.md); [Engine Sandbox](./ENGINE-SANDBOX.DESIGN.md); the LMDE proxy layer as defined in [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md), Deadline proxy  
> **Origin:** [concept: decision-arena](../concepts/decision-arena/CONCEPT.md), issue #382

---

## Overview

The Decision Arena is the LMDE service that answers typed decision
questions -- yes/no, pick-one, rubric -- with per-option probabilities,
from a decision model running on the laptop. It speaks the Jev/SystemOne
API, sits behind the LMDE proxy layer, which feeds the model one request
at a time with interactive callers ahead of batch work, and runs inside the
Engine Sandbox. Its first caller is the ocrinator; git hooks and local
ci-magic runs come later, and callers from off the laptop after the MVP.

---

## Goals

- **G1 Decisions on the laptop.** A `POST /v1/systemone` request to the
  arena's route returns, for every question in the request, the
  probability of each allowed option, with images accepted as base64.
  Answering needs no network access.
- **G2 One at a time, interactive first.** The model computes at most one
  request at a time. An interactive request never waits behind a queued
  batch request; within a class, requests are served in arrival order.
  Under steady interactive load, batch requests wait, and past the queue
  deadline they get the busy answer.
- **G3 Never hang, and say why.** Every request gets an answer, and the
  caller can tell these apart by status code alone:

  | Answer | When | Retry? |
  |---|---|---|
  | busy | Not started within the queue deadline | Yes, after a delay |
  | down | Arena not serving (stopped, loading, or refused); within 5 s | Not before the arena is back |
  | timed out | Started, but ran past the in-flight ceiling | No, not automatically |
  | failed | The arena crashed while computing this request | No, not automatically |
  | rejected | Malformed, oversized, or not from a local SystemOne client (4xx) | No |

  The codes are chosen in code, verified distinct as behaviors, and part of
  the caller contract.
- **G4 Confined and verified.** The arena runs under the Engine Sandbox, and
  before every start its code -- the loader, every executable file of the
  pinned model revision, and its Python environment -- matches what was
  reviewed. Either check failing holds the arena down.
- **G5 Runs unattended, visibly.** The arena and its route start at login
  and restart after a crash, needing neither a human nor an unlocked
  1Password. One LMDE status command shows the arena's state and, when it
  is down, why (loading, refused by the sandbox, code mismatch).
- **G6 The model is configuration, and it is named.** Changing the served
  model -- the 4-bit conversion, or another SystemOne-compatible decision
  model -- changes the arena's configuration and pinned files, and no
  caller code. Every response and `GET /v1/models` name the served
  repository and revision, so callers can tie thresholds and journals to
  the model that answered.
- **G7 The everyday ollama is untouched.** In normal operation, installing,
  running or removing the arena leaves `127.0.0.1:11434`, its configuration
  and its model store unchanged. Under compromise of the arena this is not
  guaranteed until the arena hardens (Security Considerations).

---

## Non-Goals

- **Callers off the laptop.** Through a cloudflared tunnel, after the MVP
  (Todd, 2026-10-03: "tunnel after mvp").
- **Authentication and refusing image URLs in the server.** Deferred to
  issue #401. The MVP is loopback-only, and its callers send base64.
- **Performance targets.** Not designed now (Todd, 2026-10-03: "we can worry
  about performance later"). Measured as of 2026-10-03: about 5.5 s for one
  page scan, 0.7 s for a short text question (issue #382).
- **Memory contention** with the everyday ollama or other GPU users.
  Operational, not design (Todd, 2026-10-03).
- **Requests in parallel on the GPU.** The model reads its whole input in
  one compute-bound pass; parallel requests share the GPU and finish no
  sooner.
- **Model management through the API.** Pinned files are installed by a
  setup step, never pulled by a request.
- **Callers' adapters and deadlines.** Each caller's `DecisionPort` adapter,
  and how long it is willing to wait, are that caller's design (the
  ocrinator's is its task-045; a git hook's is the hook's).
- **Choosing when to use a decision model.** The `decision-models` skill
  (9atatimer/Skills); comparing against hosted Jev is the Decision Index's
  job (Future Considerations).

---

## Architecture Overview

```
 ocrinator (batch)        git hook / ci-magic (interactive)      [later: tunnel]
       |                              |
       |  POST /v1/systemone          |  POST /v1/systemone
       v                              v
+----------------- LMDE proxy layer (HAProxy, LaunchAgent) ---------------+
|  arena route                                                            |
|    batch listener        127.0.0.1:<batch-port>        priority: low    |
|    interactive listener  127.0.0.1:<interactive-port>  priority: high   |
|    refuses: oversized body, non-JSON body, foreign Host -> rejected     |
|    one backend: one request in flight, held until the model finishes    |
|    queue deadline -> busy;  in-flight ceiling -> timed out + restart    |
|    backend not listening -> down                                        |
+-------------------------------------------------------------------------+
       |  loopback only, one request at a time
       v
+---------------- Engine Sandbox (arena policy) --------------------------+
|  launcher: sandbox probe + code digests, before every start             |
|  arena server, 127.0.0.1:<arena-port>                                   |
|    SystemOne HTTP contract; names the served model and revision         |
|    decision model from pinned files in the arena tree                   |
|    MLX on the Metal GPU                                                 |
+-------------------------------------------------------------------------+

 everyday ollama, 127.0.0.1:11434 -- unchanged, not involved

 Callers depend on the SystemOne contract, the class listeners and the
 answer codes -- never on the model, the server or the proxy behind them.
```

---

## Design

### Arena server (tds-utils LMDE)

| Responsibility | Details |
|---|---|
| Serve the contract | `POST /v1/systemone` with the Jev/SystemOne request and response bodies; `GET /health`; `GET /v1/models` naming repository and revision |
| Serve one model | The model named by the arena's configuration, from its pinned files |
| Answer offline | Loads from disk only; a request never causes a download |
| Loopback only | Binds `127.0.0.1:<arena-port>`; its only client is the proxy layer |
| Warm before listening | Loads the model and answers a warmup request before accepting traffic. To verify against the as-is server; if it does not, the route treats loading as down until the first health answer |
| Log no bodies | Neither the server nor the route writes a request or response body anywhere |
| Start confined and verified | Launched through the Engine Sandbox launcher, after the code digests match |
| Start and restart | A LaunchAgent, LMDE pattern, restart on crash |

**The first server** is the community MLX loader's own `clef_mlx.py
serve`, from `mlx-community/clef-flash-8bit`, used as-is (Todd, 2026-10-03:
"just use it"). Its gaps -- no authentication, and fetching any `http(s)`
image URL a request names -- are issue #401, and they are why the arena stays
loopback-only until that issue closes. Guarantees above that the as-is
server cannot meet by itself (naming the revision in responses, for one)
are met by the arena's configuration where possible, and otherwise move to
issue #401 rather than being assumed.

### The arena's route on the LMDE proxy layer

The proxy layer is HAProxy (`lmde/TECH_RADAR.md`, Adopt). The arena is one
route on it, beside the Ollama Gateway's and any other tenant's.

| Responsibility | Details |
|---|---|
| One in flight | The backend admits one request at a time. A request whose caller disconnects keeps the slot until the model finishes it, so the next request never meets a busy GPU |
| Caller class by listener | A caller's class is the loopback listener it connects to. A caller changes its base URL to change class; it adds no header and no client code |
| Priority | Queued interactive requests are served before queued batch requests; arrival order within a class |
| One queue deadline | A single deadline for the backend's queue; past it, busy. Interactive callers wanting less wait set their own client deadline |
| In-flight ceiling | A request computing past the ceiling gets timed out, and the arena is restarted, so no orphaned computation precedes the next request |
| Request hygiene | Bodies over the size limit, bodies that are not JSON, and requests whose Host is not the listener's loopback address are rejected before they reach the arena |
| Distinct answers | Busy, down, timed out and failed are distinguishable by status code alone (G3) |
| Tenants stay apart | The arena route's queue, limits and backend apply only to arena traffic |

### Arena tree and policy (Engine Sandbox)

The arena's one tree, under `~/.local/`, holds everything it runs from:

| Subtree | Holds | Arena may write? |
|---|---|---|
| `env` | The pinned Python environment (MLX, mlx-vlm), from a lockfile | Not in the first cut's policy; integrity by digest before every start |
| `model` | The pinned revision: loader, safetensors weights, configuration | As above |
| `home` | The arena's `HOME`: caches, scratch | Yes |

| Policy field | Arena value |
|---|---|
| Allow-list | The arena tree |
| Protected trees and secrets | The Engine Sandbox baseline, inherited -- including the Ollama Gateway's run token |
| Hardening rules | None in the first cut; the arena's hardening is issue #401 and the Engine Sandbox's per-engine pass |

### Code integrity

| Responsibility | Details |
|---|---|
| Pinned | Repository, revision and environment lockfile are configuration; setup installs exactly those |
| Reviewed | The loader and every other executable file in the revision are read before a revision is pinned; a revision bump re-reads them. Weights are safetensors only -- a revision carrying pickle-format weights is refused |
| Verified before every start | The launcher compares the digests of the loader, the revision's executable files, the weights index and the environment against the reviewed digests. A mismatch holds the arena down with reason "code mismatch" |

---

## Behaviors and Interfaces

The arena is composition: an off-the-shelf server behind a configured
route, started by the Engine Sandbox. Its seams are the **SystemOne
contract** (callers to whatever serves it), the **class listeners and
answer codes** (callers to the route), `ArenaConfig` (the model),
`WeightStorePort` (where pinned files come from) and the Engine Sandbox's
`ConfinerPort`. HTTP rows exercise the contract through the route.

| Behavior | Use case (signature) | Ports it needs | Given / When / Then |
|---|---|---|---|
| A caller gets a decision | SystemOne contract on a class listener | SystemOne contract | Given a READY arena, When a caller posts one choice and one yes/no question with a base64 image, Then every option of both questions has a probability, and the response names the repository and revision |
| One request computes at a time | SystemOne contract, batch listener | class listeners | Given two batch requests posted together, When the first is computing, Then the second has not reached the server |
| Interactive goes first | SystemOne contract, interactive listener | class listeners | Given a batch request in flight and a batch request queued, When an interactive request arrives, Then it is served before the queued batch request |
| A busy arena says so | SystemOne contract | answer codes | Given a request in flight longer than the queue deadline, When another waits past it, Then it gets busy |
| A down arena says so | SystemOne contract | answer codes | Given the server not listening, When a caller posts, Then it gets down within 5 s |
| A runaway request is ended | SystemOne contract | answer codes | Given a request computing past the in-flight ceiling, When the ceiling passes, Then it gets timed out and the arena restarts before admitting the next request |
| An abandoned request keeps the slot | SystemOne contract | class listeners | Given a caller disconnects mid-request, When the next request is queued, Then it is not admitted until the model finishes the abandoned one |
| A crash mid-request is not retried for the caller | SystemOne contract | answer codes | Given the server crashes while computing, When the caller's request ends, Then it gets failed, and queued requests get down |
| Junk is rejected at the route | SystemOne contract | answer codes | Given an oversized body, a non-JSON body, or a foreign Host header, When posted, Then rejected (4xx), and the server never sees it |
| A bad request is the caller's fault | SystemOne contract | answer codes | Given an unknown question type, When posted, Then a 4xx, not a 5xx |
| The arena starts confined | `start_arena(config: ArenaConfig, *, launch: launch_confined, confiner: ConfinerPort) -> LaunchVerdict` | ConfinerPort | Given passing digests and a passing probe, When launchd starts the arena, Then it serves under the policy |
| Changed code holds it down | (same use case; error path) | ConfinerPort | Given a loader that differs from its reviewed digest, When launchd starts the arena, Then it does not serve, and status says "code mismatch" |
| The gateway's token is out of reach | (same use case) | ConfinerPort | Given the gateway's run token on the machine, When the arena is probed, Then the token is unretrievable (Engine Sandbox baseline) |
| The arena restarts after a crash | (same use case, driven by launchd) | ConfinerPort | Given a READY arena, When its server is killed, Then within launchd's relaunch it is READY again, with probe and digests rerun |
| Down says why | `arena_status(config: ArenaConfig) -> ArenaStatus` | ConfinerPort | Given the probe refused the last start, When status is asked, Then it reports down with the refused assertion |
| A model swap is configuration | `install_weights(config: ArenaConfig, *, store: WeightStorePort) -> InstalledWeights` | WeightStorePort | Given a configuration naming a different repository and revision, When setup runs and the arena restarts, Then callers get answers naming the new revision with no change of their own |
| Setup installs exactly what was pinned | (same use case) | WeightStorePort | Given a pinned revision, When setup runs, Then exactly that revision is on disk, and a pickle-format weight file or an unreviewed loader stops setup |
| The everyday ollama is untouched | `install_arena` / `remove_arena` (setup) | -- | Given the everyday ollama's configuration and store, When the arena is installed, run and removed, Then both are byte-identical and 11434 still answers |

---

## State Machine

The arena as a caller sees it.

| State | Condition | A request gets |
|---|---|---|
| DOWN | Server not listening: stopped, loading, refused by the sandbox, or code mismatch | down within 5 s |
| READY | Server listening, nothing in flight | The answer |
| BUSY | Server listening, one request in flight | Queued by class; the answer, or busy past the queue deadline |

```
            probe + digests pass, model warm, listening
 +------+ -----------------------------------------> +-------+
 | DOWN |                                            | READY |
 +------+ <----------------------------------------- +-------+
     ^      server exits / crashes                    |    ^
     |                                   request in   |    | request done,
     |                                                v    | queue empty
     |      crash, or in-flight ceiling (restart)  +------+
     +-------------------------------------------- | BUSY |
                                                   +------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| DOWN | READY | Server starts listening | Digests matched, probe passed, warmup answered |
| READY | BUSY | A request is admitted | Queue was empty |
| BUSY | BUSY | The request in flight completes | Queue not empty; next by class, then arrival |
| BUSY | READY | The request in flight completes | Queue empty |
| BUSY | DOWN | The in-flight ceiling passes | The request gets timed out; the arena is restarted; queued requests get down |
| BUSY | DOWN | Server exits or crashes | The request in flight gets failed; queued requests get down |
| READY | DOWN | Server exits or crashes | launchd relaunches it through the launcher |

A failed probe or a code mismatch holds the arena in DOWN until fixed, and
the status command says which.

---

## Data Model

No database.

```
ArenaConfig (tds-utils lmde/components/decision-arena)
+-- model repository   e.g. mlx-community/clef-flash-8bit
+-- model revision     pinned commit; the only revision setup installs
+-- reviewed digests   loader, the revision's executable files, weights
                       index, environment lockfile
+-- arena-port         the server's loopback port
+-- class listeners    one loopback port per caller class (interactive, batch)
+-- queue deadline     one, for the backend's queue
+-- in-flight ceiling  one
+-- body size limit    one
+-- arena tree         under ~/.local/: env, model, home

ArenaStatus
+-- state              DOWN | READY | BUSY
+-- reason             when DOWN: loading | refused(<assertion>) | code mismatch | stopped
+-- serving            repository + revision, when not DOWN
```

---

## Data Warehouse

Nothing is ledgered by the arena. Each response carries its token count,
latency and the served revision; callers record what they need (the
ocrinator's `llm_call` journal). No body is written to disk by the server or
the route: access logs carry method, path, status, class and latency only.

---

## Security Considerations

- **Who is on loopback.** Any local process can use the arena: there is no
  authentication (issue #401). That includes the other confined engines --
  a compromised external ollama could drive the arena -- accepted until the
  engines' loopback hardening.
- **Web pages are on loopback too.** A page can send a simple POST to
  `127.0.0.1`, and DNS rebinding can let it read the answer. The route
  rejects non-JSON bodies and foreign Host headers, which closes both
  without any client change.
- **Image URLs are fetched by the server.** A request naming an `http(s)`
  image makes the laptop fetch it -- server-side request forgery, including
  against 11434. Local callers send base64; the arena is not reachable off
  the laptop until issue #401 closes.
- **Third-party code runs on every request,** from a tree the arena can
  write in the first cut. Persistence across restarts is closed by the
  digest check before every start (G4); tampering within one run is not,
  until the arena hardens.
- **Credentials.** The arena inherits the Engine Sandbox baseline: protected
  trees and every protected secret, the gateway's run token included, are
  out of reach.
- **Caller class is self-asserted.** Any local process can use the
  interactive listener and delay batch work. Availability only; accepted.
- **Page scans are sensitive documents.** No body is logged anywhere (Data
  Warehouse).
- **A decision is evidence, not authority.** What a caller does with a
  probability or a failure is the caller's design (the `decision-models`
  skill: a failure never takes the path a "yes" would).

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the arena lives | An LMDE sub-component, a peer of the Ollama Gateway, separate from any caller | Concept (Todd): "a peer of my ollama" |
| First callers | The ocrinator, on the laptop; callers off the laptop after the MVP | Todd, 2026-10-03: "ocrinator first. tunnel after mvp" |
| Later callers | Local git hooks and local ci-magic runs; a shared service, not a library in each caller | Todd, 2026-10-03: "leave the door open to git-hook and local ci-magic invocations" |
| Serving stack | MLX | Todd, 2026-10-03: "definitely go with mlx". Spike (issue #382): 5.5 s per page scan at 11 GiB, against 8.2 s at 24 GiB under PyTorch |
| First model | `mlx-community/clef-flash-8bit` at a pinned revision; 4-bit is the fallback | Agent's pick within the MLX ruling: matched the PyTorch reference within 0.03 on the spike pages |
| Server | `clef_mlx.py serve`, as-is | Todd, 2026-10-03: "just use it"; hardening is issue #401 |
| Queueing | HAProxy holds the queue; one request reaches the model | HAProxy adopted for exactly this (radar, 2026-10-03); the model's pass is compute-bound |
| Caller class | The loopback listener a caller connects to | Existing SystemOne clients (the Decision Index's `http` engine among them) take only a base URL |
| Queue deadline | One for the backend; interactive callers keep their own client deadline | HAProxy's queue timeout is per backend, and one backend per class would put two requests in flight |
| In-flight work | Held to completion if the caller leaves; ended by restart past a ceiling | The model cannot be interrupted mid-pass, so freeing the slot early would put two passes on the GPU |
| Answer contract | Busy, down, timed out and failed distinct by status code; only busy is retryable | Callers act differently on each: a batch backs off on busy, stops on down, and must not loop a request that crashes the arena |
| Request hygiene | Size limit, JSON-only, Host check at the route | The route is where limits live (Ollama Gateway, Deadline proxy); closes browser-originated requests with no client change |
| Code integrity | Digests verified before every start; safetensors only | The arena can write its own tree in the first cut; a setup-time check alone would let one compromise persist |
| Serving-stack axis | Seam = the SystemOne contract on `<arena-port>` | A hardened wrapper (issue #401), or Ollama once it serves `/v1/systemone`, swaps behind the route |
| Model axis | Seam = `ArenaConfig` | G6 |
| Weight-store axis | Seam = `WeightStorePort` in setup | Hugging Face today; a mirror later |
| Confinement | The Engine Sandbox, arena policy, inheriting the baseline | Todd, 2026-10-03: DRY with the gateway, harden separately |
| Memory contention | Not designed | Todd, 2026-10-03: operational, not design |
| Radar: MLX (`mlx`, `mlx-vlm`) | Propose Trial in `lmde/TECH_RADAR.md` with the code | Not on the LMDE radar; the arena is its first consumer |

---

## Open Questions

- **Q1 The LMDE proxy layer's own record.** The layer is defined inside the
  Ollama Gateway's Deadline proxy section, is not built, and now has a
  second tenant with requirements of its own (a priority queue, an
  in-flight ceiling). Extract it into its own design record, as the sandbox
  was, and let whichever of the gateway and the arena is built first build
  the layer? Recommended: yes.
- **Q2 The first step.** The ocrinator is batch-only, and the interactive
  class has no caller until hooks arrive. Recommended: the MVP ships the
  route with the batch listener and the G3 answers (which the ocrinator's
  overnight run needs), and the interactive listener arrives with the first
  interactive caller. The alternative -- the ocrinator talking to the
  server directly before the layer exists -- gives up G3, including never
  hanging.

---

## Rejections

- **PyTorch on the Metal GPU.** Slower than MLX and twice the memory on the
  spike, with no fast kernel for the model's linear-attention layers.
- **A library inside each caller.** Every hook, CI run and batch would load
  11 GiB of weights, and nothing would order them on the one GPU.
- **Requests in parallel on the GPU.** Compute-bound; parallel requests
  finish no sooner, and the wait stops being predictable.
- **Open-source nginx or Caddy as the queue.** Neither queues requests to a
  busy backend with priority.
- **Caller class by request header.** Needs a client change in every
  SystemOne client; a listener per class needs none.
- **A queue deadline per class.** Not expressible on one HAProxy backend,
  and two backends would put two requests in flight.
- **Freeing the slot when a caller disconnects.** The model keeps computing
  the abandoned request, so the next request would share the GPU.
- **Sharing the Ollama Gateway's tunnel.** One leaked gateway credential
  would reach the arena; the arena gets its own tunnel after the MVP
  (issue #382).
- **Ollama as the server today.** The installed and latest Homebrew ollama
  (0.34.4) does not run the decision head.
- **Downloading weights on demand.** A request must never trigger a
  multi-gigabyte download or run an unreviewed revision.

---

## Future Considerations

- **Callers off the laptop.** The arena's own tunnel, Access application
  and service tokens, declared in tds-internal IaC like the gateway's, after
  the MVP and after issue #401.
- **Hardening.** Issue #401 (auth, image URLs), then the arena's Engine
  Sandbox pass: outbound network and loopback denied (G1 says it needs
  neither), and the `env` and `model` subtrees read-only.
- **Profiling and comparison.** The Decision Index's `http` engine against
  the arena's route gives the standard capability score and latency, and
  the same run against hosted Jev gives the baseline.
- **Another serving stack.** Ollama, once a release serves
  `/v1/systemone`; a swap behind the serving-stack seam.
- **Clef 27B.** A model change (G6), if the ocrinator measurement shows
  flash is not enough.
- **Metrics** in the LMDE observability stack: queue depth, answers by code
  and class, latency by class.

---

## Related Documents

- [Engine Sandbox](./ENGINE-SANDBOX.DESIGN.md) -- the confinement the arena
  runs under.
- [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md) -- the peer engine, and the
  current definition of the LMDE proxy layer.
- [LMDE](./LMDE.DESIGN.md) -- the platform.
- [concept: decision-arena](../concepts/decision-arena/CONCEPT.md) -- origin
  (non-binding).
- Issue #382 -- the problem record, the spike findings and the rulings.
- Issue #401 -- hardening the server before any tunnel.
- The `decision-models` skill (9atatimer/Skills) -- how callers put a
  judgement behind a `DecisionPort`.
