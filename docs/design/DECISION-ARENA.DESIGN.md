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
API, sits behind the LMDE proxy layer, which queues callers one at a time
with interactive callers ahead of batch work, and runs inside the Engine
Sandbox. Its first caller is the ocrinator; git hooks and local ci-magic
runs come later, and callers from off the laptop come after the MVP.

---

## Goals

- **G1 Decisions on the laptop.** A `POST /v1/systemone` request to the
  arena's route on the LMDE proxy layer returns, for every question in the
  request, the probability of each allowed option, with images accepted as
  base64. Answering needs no network access.
- **G2 One at a time, interactive first.** The model receives at most one
  request at a time. Waiting requests are served by caller class:
  interactive before batch, and in arrival order within a class. An
  interactive request that arrives during a batch run waits for at most the
  one request in flight.
- **G3 Never hang.** A request that cannot start within its class's queue
  deadline gets an HTTP 503 that says the arena is busy. A request sent
  while the arena is down gets an HTTP 503 within 5 seconds. Both are
  distinguishable from a 4xx for a bad request.
- **G4 Confined.** The arena runs under the Engine Sandbox with its own
  policy and never starts unconfined.
- **G5 Runs unattended.** The arena and its route start at login and
  restart after a crash, needing neither a human nor an unlocked 1Password.
- **G6 The model is configuration.** Changing the served model -- to the
  4-bit conversion, or to another SystemOne-compatible decision model --
  changes the arena's configuration and its pinned weights, and no caller.
- **G7 The everyday ollama is untouched.** Installing, running or removing
  the arena leaves `127.0.0.1:11434`, its configuration and its model store
  unchanged.

---

## Non-Goals

- **Callers off the laptop.** Through a cloudflared tunnel, after the MVP
  (Todd, 2026-10-03: "tunnel after mvp").
- **Authentication and refusing image URLs.** Deferred to issue #401. The
  MVP is loopback-only, and its callers send images as base64.
- **Performance targets.** Not designed now (Todd, 2026-10-03: "we can worry
  about performance later"). Measured as of 2026-10-03: about 5.5 s for one
  page scan and 0.7 s for a short text question (issue #382).
- **Memory contention** with the everyday ollama or other GPU users.
  Operational, not design (Todd, 2026-10-03).
- **Running requests concurrently on the GPU.** The model reads its whole
  input in one compute-bound pass, so parallel requests would share the GPU
  rather than finish sooner.
- **Model management through the API.** Weights are installed by a setup
  step at a pinned revision, never pulled by a request.
- **The callers' adapters.** Each caller's `DecisionPort` adapter is that
  caller's design (the ocrinator's is its task-045).

---

## Architecture Overview

```
 ocrinator (batch)        git hook / ci-magic (interactive)      [later: tunnel]
       |                              |
       |  POST /v1/systemone          |  POST /v1/systemone
       v                              v
+----------------- LMDE proxy layer (HAProxy, LaunchAgent) ---------------+
|  arena route                                                            |
|    batch listener    127.0.0.1:<batch-port>        -> priority: low     |
|    interactive lstnr 127.0.0.1:<interactive-port>  -> priority: high    |
|    one backend, at most 1 request in flight; the rest queue by class    |
|    per-class queue deadline -> 503 busy; backend down -> 503 at once    |
+-------------------------------------------------------------------------+
       |  loopback only, one request at a time
       v
+------------------- Engine Sandbox (arena policy) -----------------------+
|  arena server, 127.0.0.1:<arena-port>                                   |
|    SystemOne HTTP contract                                              |
|    decision model: weights at a pinned revision in the arena's tree     |
|    MLX on the Metal GPU                                                 |
+-------------------------------------------------------------------------+

 everyday ollama, 127.0.0.1:11434 -- unchanged, not involved

 Callers depend on the SystemOne contract and on a listener per class,
 never on the model, the serving stack or the proxy behind them.
```

---

## Design

### Arena server (tds-utils LMDE)

| Responsibility | Details |
|---|---|
| Serve the contract | `POST /v1/systemone` with the Jev/SystemOne request and response bodies; `GET /health` and `GET /v1/models` for status |
| Serve one model | The model named by the arena's configuration, from weights at a pinned revision in the arena's own tree |
| Answer offline | Loads weights from disk only; a request never causes a download |
| Loopback only | Binds `127.0.0.1:<arena-port>`; its only client is the proxy layer |
| Warm before listening | Loads the model and answers a warmup request before accepting traffic, so the first real caller never pays the load |
| Start confined | Launched by the Engine Sandbox launcher under the arena's policy |
| Start and restart | A LaunchAgent, LMDE pattern, restart on crash |

**The first serving stack** is the community MLX loader's own server,
`clef_mlx.py serve`, from `mlx-community/clef-flash-8bit`, used as-is (Todd,
2026-10-03: "just use it"). Its known gaps -- no authentication, and fetching
any `http(s)` image URL a request names -- are issue #401, and they are why
the arena stays loopback-only until that issue closes.

### The arena's route on the LMDE proxy layer

The proxy layer is HAProxy (`lmde/TECH_RADAR.md`, Adopt). The arena is one
route on it, beside the Ollama Gateway's and any other tenant's.

| Responsibility | Details |
|---|---|
| One in flight | The backend admits at most one request at a time; the layer holds the rest |
| Caller class by listener | A caller's class is the loopback listener it connects to, one per class. A caller changes its base URL to change class; it adds no header and no client code |
| Priority | Queued interactive requests are served before queued batch requests; arrival order within a class |
| Bounded wait | Each class has its own queue deadline; past it, HTTP 503 (busy). Values are code, not design |
| Fast failure | Backend not listening: HTTP 503 at once, never a hang |
| Tenants stay apart | The arena route's queue, deadlines and backend apply only to arena traffic |

### Arena confinement policy (Engine Sandbox)

| Field | Arena value |
|---|---|
| Home allow-list | The arena's config tree under `~/.local/` (also its `HOME`), which holds the pinned weights |
| Named secrets | None in the first cut |
| Hardening rules | None in the first cut; issue #401 and the Engine Sandbox's per-engine hardening |

### Weights

| Responsibility | Details |
|---|---|
| Pinned | Repository id and revision are configuration; the setup step installs exactly that revision |
| Reviewed | The loader shipped with the weights is executable third-party code; it is read before a revision is pinned, and a revision bump re-reads it |
| In one tree | The weights live under the arena's config tree, the policy's one allow-listed tree |

---

## Behaviors and Interfaces

The arena is composition: its contract is the SystemOne HTTP API, served
by an off-the-shelf server, behind a configured route. The tds-utils code it
adds is a launcher entry over the Engine Sandbox, the route's configuration
and the setup step. Rows name the entry point that carries each behavior;
where that is the HTTP contract, the row says so.

| Behavior | Use case (signature) | Ports it needs | Given / When / Then |
|---|---|---|---|
| A caller gets a decision | SystemOne contract: `POST /v1/systemone` on the caller's class listener | the decision engine (behind the contract) | Given a running arena, When a caller posts a request with one choice and one yes/no question and a base64 image, Then the response holds every option's probability for both questions |
| Interactive goes first | SystemOne contract, interactive listener | the proxy layer | Given a batch request in flight and a batch request queued, When an interactive request arrives, Then it is served before the queued batch request |
| A busy arena says so | SystemOne contract, any listener | the proxy layer | Given a request in flight that outlasts a class's queue deadline, When a request of that class waits past it, Then it gets HTTP 503 (busy), not a hang |
| A down arena says so at once | SystemOne contract, any listener | the proxy layer | Given the arena server not listening, When a caller posts, Then it gets HTTP 503 within 5 s |
| A bad request is the caller's fault | SystemOne contract | the decision engine | Given a request with an unknown question type, When it is posted, Then the response is HTTP 400, not 5xx |
| The arena starts confined | `start_arena(config: ArenaConfig, *, sandbox: launch_confined) -> LaunchVerdict` | Engine Sandbox (ConfinerPort) | Given the arena policy's probe passes, When launchd starts the arena, Then it serves under the policy |
| The arena refuses to start unconfined | (same use case; error path) | Engine Sandbox (ConfinerPort) | Given the probe fails, When launchd starts the arena, Then it does not serve, and both listeners answer 503 |
| Weights are what was pinned | `install_weights(config: ArenaConfig, *, store: WeightStorePort) -> InstalledWeights` | the weight store (Hugging Face today) | Given a pinned repository and revision, When setup runs, Then exactly that revision is on disk, and a loader that differs from the reviewed one stops setup |

---

## State Machine

The arena as a caller sees it.

| State | Condition | A request gets |
|---|---|---|
| DOWN | Arena server not listening: stopped, loading, or refused by the sandbox | HTTP 503 within 5 s |
| READY | Server listening, nothing in flight | The answer |
| BUSY | Server listening, one request in flight | Queued by class; the answer, or HTTP 503 past the class deadline |

```
            server listening (probe passed, model warm)
 +------+ -----------------------------------------> +-------+
 | DOWN |                                            | READY |
 +------+ <----------------------------------------- +-------+
     ^      server exits / crashes                    |    ^
     |                                   request in   |    | request done,
     |                                                v    | queue empty
     |      server exits / crashes                 +------+
     +-------------------------------------------- | BUSY |
                                                   +------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| DOWN | READY | Server starts listening | The sandbox probe passed and the warmup request answered |
| READY | BUSY | A request is admitted | Queue was empty |
| BUSY | BUSY | A request completes | Queue not empty; next by class, then arrival |
| BUSY | READY | A request completes | Queue empty |
| READY | DOWN | Server exits or crashes | launchd relaunches it through the sandbox |
| BUSY | DOWN | Server exits or crashes | The request in flight fails with 5xx; queued requests get 503 |

A failing sandbox probe holds the arena in DOWN until it passes (Engine
Sandbox, State Machine).

---

## Data Model

No database.

```
ArenaConfig (tds-utils lmde/components/decision-arena)
+-- model repository   e.g. mlx-community/clef-flash-8bit
+-- model revision     pinned commit; the only revision setup installs
+-- reviewed loader    digest of the loader read at pinning
+-- arena-port         the server's loopback port
+-- class listeners    one loopback port per caller class (interactive, batch)
+-- queue deadlines    one per class
+-- config tree        under ~/.local/; the arena's HOME and its one
                       allow-listed tree; holds the weights
```

---

## Data Warehouse

Nothing is ledgered by the arena. Each response carries its token count and
latency; callers record what they need (the ocrinator's `llm_call` journal).
Request contents are never written to disk by the arena.

---

## Security Considerations

- **No authentication on loopback.** Any local process can use the arena.
  Accepted for the loopback-only MVP; issue #401 before any tunnel.
- **Image URLs are fetched by the server.** A request naming an `http(s)`
  image makes the laptop fetch it -- server-side request forgery, including
  against loopback services such as 11434. MVP callers send base64; the
  arena is not reachable off the laptop until issue #401 closes.
- **Third-party code runs on every request.** The loader is pinned by
  revision and read before pinning; setup refuses a loader that differs
  from the reviewed digest.
- **A hostile state cannot reach credentials.** Images and text under
  judgement are untrusted; the Engine Sandbox's allow-list holds whatever
  the model or loader is induced to do. Network and loopback are open until
  the arena hardens (accepted, per the Engine Sandbox).
- **A decision is evidence, not authority.** What a caller does with a
  probability, including on 503, is the caller's design (the
  `decision-models` skill: a failure never takes the path a "yes" would).

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the arena lives | An LMDE sub-component, a peer of the Ollama Gateway, separate from any caller | Concept (Todd): "a peer of my ollama" |
| First callers | The ocrinator, on the laptop; callers off the laptop after the MVP | Todd, 2026-10-03: "ocrinator first. tunnel after mvp" |
| Later callers | Local git hooks and local ci-magic runs; the service is shared, not a library in each caller | Todd, 2026-10-03: "leave the door open to git-hook and local ci-magic invocations" |
| Serving stack | MLX | Todd, 2026-10-03: "definitely go with mlx". Spike (issue #382): 5.5 s per page scan at 11 GiB, against 8.2 s at 24 GiB under PyTorch on the GPU |
| First model | `mlx-community/clef-flash-8bit` at a pinned revision; 4-bit is the fallback | Agent's pick within the MLX ruling: matched the PyTorch reference within 0.03 on the spike pages; fits in 11 GiB |
| Server | The loader's own `clef_mlx.py serve`, as-is | Todd, 2026-10-03: "just use it"; hardening is issue #401 |
| Queueing | The LMDE proxy layer (HAProxy) holds the queue; at most one request reaches the model | HAProxy adopted for exactly this (radar, 2026-10-03); the model's pass is compute-bound, so parallelism buys nothing |
| Caller class | The loopback listener a caller connects to | Existing SystemOne clients (the Decision Index's `http` engine among them) take only a base URL; no client change is needed to choose a class |
| Serving-stack axis | Seam = the SystemOne HTTP contract on `<arena-port>` | A different server -- a hardened wrapper (issue #401), or Ollama if it serves `/v1/systemone` -- swaps behind the route with no caller change |
| Model axis | Seam = `ArenaConfig` (repository, revision, reviewed loader) | G6: a model change is configuration, not code |
| Weight-store axis | Seam = `WeightStorePort` in the setup step | Hugging Face today; a mirror or local copy later |
| Confinement | The Engine Sandbox, with the arena's own policy | Todd, 2026-10-03: DRY with the gateway's sandbox, harden separately |
| Memory contention | Not designed | Todd, 2026-10-03: operational, not design |
| Radar: MLX (`mlx`, `mlx-vlm`) | Propose Trial in `lmde/TECH_RADAR.md` with the code | Not on the LMDE radar; the arena is its first consumer |

---

## Open Questions

- **Q1 The LMDE proxy layer's own record.** The layer is defined inside the
  Ollama Gateway's Deadline proxy section, is not built, and now has a
  second tenant with requirements of its own (a priority queue). Should it
  be extracted into its own design record, as the sandbox was, and does
  whichever of the gateway and the arena is built first build the layer?
- **Q2 Before the layer exists.** The arena can bind loopback and serve the
  ocrinator directly while the layer is unbuilt, without G2 and G3. Is that
  an acceptable first step, or does the arena wait for the layer?

---

## Rejections

- **PyTorch on the Metal GPU.** Slower than MLX and twice the memory on the
  spike (8.2 s per page at 24 GiB), with no fast kernel for the model's
  linear-attention layers.
- **A library inside each caller.** Every hook, CI run and batch would load
  11 GiB of weights, and nothing would order them on the one GPU.
- **Requests in parallel on the GPU.** The model's pass is compute-bound;
  parallel requests share the GPU and finish no sooner, and the wait stops
  being predictable.
- **Open-source nginx or Caddy as the queue.** Neither queues requests to a
  busy backend with priority.
- **Caller class by request header.** Needs a client change in every
  SystemOne client; a listener per class needs none.
- **Sharing the Ollama Gateway's tunnel.** One leaked gateway credential
  would reach the arena, and the gateway's goals would be rewritten for a
  second engine; the arena gets its own tunnel after the MVP (issue #382).
- **Ollama as the server today.** The installed and latest Homebrew ollama
  (0.34.4) does not run the decision head.
- **Downloading weights on demand.** A request must never trigger a
  multi-gigabyte download or run an unreviewed loader revision.

---

## Future Considerations

- **Callers off the laptop.** The arena's own tunnel, Access application
  and service tokens, declared in tds-internal IaC like the gateway's, after
  the MVP and after issue #401.
- **Hardening.** Issue #401 (auth, image URLs), then the arena's Engine
  Sandbox hardening (network, loopback).
- **Profiling.** The Decision Index's `http` engine points at the arena's
  route and gives the standard capability score and latency for the served
  model.
- **Another serving stack.** Ollama, once a release serves
  `/v1/systemone`; a swap behind the serving-stack seam.
- **Clef 27B.** A model change (G6), if the ocrinator measurement shows
  flash is not enough.
- **Metrics** in the LMDE observability stack: queue depth, 503s by class,
  latency by class.

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
