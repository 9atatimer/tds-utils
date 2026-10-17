# Decide Route

> **Status:** DRAFT  
> **Date:** 2026-10-16  
> **Authors:** Todd Stumpf, Claude (Opus 5.5)  
> **Depends on:** [LMDE](./LMDE.DESIGN.md); the LMDE proxy layer as defined in [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md), Deadline proxy  
> **Origin:** [concept: decide-route](../concepts/decide-route/CONCEPT.md), Issue#382

---

## Overview

The decide route is the one place on the laptop where local tools ask
decision questions. A tool names a model and sends its questions. The
route answers from that model, hosted or local, and the tool never holds
a credential.

---

## Problem and approach

**The problem.** Every local tool that wants a decision has to know where
the model lives. Asking the hosted model today means holding its
credential and reading it from 1Password on every call, so it fails
whenever 1Password is locked. Moving a tool from hosted to local means
re-plumbing that tool. Each new caller repeats all of it.

**The approach.**

- One door on the laptop, reachable only from the laptop.
- The door speaks the public decision contract that clients already use,
  so a client changes its address and nothing else.
- The model a request names decides where it is answered. The door's
  catalog says which models it serves and where each one lives.
- The door holds the hosted credential. Tools hold none.
- A request is answered by the model it names or refused. The door never
  substitutes another model.

**Tradeoffs.**

| Given up | Why it is worth it |
|---|---|
| Any local process can spend the hosted budget through the door | The hosted service's existing spend cap still applies, and the door is unreachable off the laptop |
| A tool cannot ask for "whichever model is available" | Two models' probabilities are not interchangeable, so a silent switch would break a caller's thresholds |
| Cloud sessions do not use the door | They have no LMDE; they keep calling the hosted model directly, as today |
| One more always-on service on the laptop | It replaces a credential read and a configuration in every tool |

---

## Goals

- **G1 One door.** A local tool sends a decision request to one address on
  the laptop and gets back, for every question, the probability of each
  allowed option.
- **G2 Existing clients work.** A client of the public decision contract
  works through the door after changing only its address.
- **G3 No credential, no unlock.** Asking needs no credential from the
  tool and works while 1Password is locked.
- **G4 The named model or nothing.** A request is answered by the model it
  names, or refused with the reason. Every answer names the model that
  produced it.
- **G5 Hosted from day one.** The hosted decision models answer through
  the door at the MVP.
- **G6 The catalog is configuration.** Adding a model, hosted or local,
  changes the door's catalog and no tool.
- **G7 Laptop only.** Nothing off the laptop, and no web page open in a
  browser on it, can get a decision from the door.
- **G8 Never hang, and say why.** Every request gets an answer within a
  bound, and the caller can tell the kinds of failure apart (Design,
  Answers).
- **G9 Hosted spend stays capped and visible.** Requests through the door
  count against the hosted service's existing spend cap and appear in its
  log.
- **G10 Runs unattended, visibly.** The door starts at login and restarts
  after a crash, needing no human. One command shows whether it is serving
  and, when it is not, why.
- **G11 Bodies stay out of logs.** No request or response body is written
  to disk on the laptop. Hosted requests ask the hosted service not to log
  bodies unless the owner turns that on.

---

## Non-Goals

- **A local model in the MVP.** The decision arena joins later as a
  catalog entry, with its own design (concept: decision-arena).
- **Ordering callers.** A queue that puts git hooks ahead of batch work
  belongs to the local backend, which is the only one with a single
  scarce GPU.
- **Callers off the laptop.** No tunnel, now or in this design.
- **Cloud sessions.** They keep calling the hosted model directly.
- **Authenticating local callers.** The laptop's loopback is the
  boundary.
- **"Whichever is available."** Deferred; see Open Questions.
- **Changing the hosted service's spend rules or credentials' lifecycle.**
  Those are tds-internal's.
- **Performance targets.** The door adds a hop; it is not designed for a
  latency figure.

---

## Design

### The door

| Responsibility | Rule |
|---|---|
| One address | The door listens at one address, on the laptop only |
| One contract | Requests and answers are the public decision contract, unchanged in shape |
| Every question answered | An answer carries a probability for each allowed option of every question, or the request fails as a whole |
| No body kept | The door writes no body to disk, and forwards nothing it was not asked to |

### The catalog

| Rule | Detail |
|---|---|
| Names are the interface | A tool asks for a model by its catalog name |
| One name, one model | A name always means the same model; a different model gets a different name |
| Unknown is refused | A name not in the catalog is refused before anything is sent anywhere |
| Unavailable is refused | A catalog model whose backend cannot answer is refused as unavailable |
| No fallback | No name ever resolves to a second model when the first cannot answer |
| Configuration only | Entries are added and removed in the door's configuration, never in a tool |

The MVP catalog holds the hosted models that `bin/decide` reaches today.

### The credential

| Rule | Detail |
|---|---|
| Held by the door | The hosted credential is the door's, not any tool's |
| Seeded once | A human seeds it once from its 1Password item; after that the door needs no unlocked 1Password |
| Never shown | It never appears in an answer, a log, a status output or a process listing |
| Callers cannot override it | A credential a caller sends is never forwarded |

### Answers

Every request ends in exactly one of these. A caller can tell them apart
without reading prose.

| Answer | When | The caller should |
|---|---|---|
| decided | The named model answered | use it |
| rejected | The request is malformed, too large, or not from a local tool | fix the request; never retry it unchanged |
| unknown model | The name is not in the catalog | fix the name |
| unavailable | The named model's backend cannot be reached, or the door is not serving | retry later or stop; never switch models |
| refused upstream | The hosted service refused: credential or spend cap | stop; a human must act |
| timed out | No answer within the request bound | retry with care; it may have cost money |

### Callers

| Caller | Rule |
|---|---|
| `bin/decide` on the laptop | Asks through the door when no hosted configuration of its own is set |
| `bin/decide` in a cloud session | Unchanged: calls the hosted model directly |
| Any other local tool | Speaks the public decision contract to the door's address |

---

## Behaviors

| Behavior | Given / When / Then |
|---|---|
| A tool gets a hosted decision | Given the door serving and a catalog hosted model, When a tool sends a request naming it with a choice and a yes/no question, Then the answer is decided and holds every option's probability for both |
| The answer names its model | Given any decided answer, When the tool reads it, Then it names the catalog model that produced it |
| No credential needed | Given a tool that sends no credential, When it asks, Then it is answered |
| A locked 1Password does not matter | Given 1Password locked after setup, When a tool asks a hosted model, Then it is answered |
| A caller's credential is not forwarded | Given a request carrying its own credential, When the door forwards it, Then the hosted service sees the door's credential only |
| An unknown model is refused | Given a name not in the catalog, When a tool asks, Then the answer is unknown model and nothing is sent to any backend |
| An unavailable model is not substituted | Given a catalog model whose backend cannot be reached, When a tool asks for it, Then the answer is unavailable and no other model answers |
| The hosted service refuses | Given a hosted refusal of the credential or the spend cap, When a tool asks, Then the answer is refused upstream |
| A slow answer is cut off | Given a backend that does not answer within the request bound, When a tool asks, Then the answer is timed out within the bound |
| A stopped door says so at once | Given the door not serving, When a tool asks, Then the tool learns unavailable within the down bound |
| A malformed request is rejected | Given a request that is not a valid decision request, When it is sent, Then the answer is rejected and no backend sees it |
| An oversized request is rejected | Given a request over the size bound, When it is sent, Then the answer is rejected and no backend sees it |
| A web page cannot ask | Given a request sent by a web page in a browser on the laptop, When it reaches the door, Then it is rejected |
| Nothing off the laptop can ask | Given a host other than the laptop, When it tries to reach the door, Then it gets no decision |
| Images pass through | Given a request with images, When a hosted model that reads images is named, Then the images reach it unchanged |
| Bodies are not logged | Given any request, When it completes or fails, Then no body is on the laptop's disk |
| Hosted spend is capped | Given door traffic, When it reaches the hosted service, Then it counts against the existing spend cap and appears in its log |
| A new catalog entry needs no tool change | Given a model added to the catalog, When a tool names it, Then it is answered with no change to the tool |
| `bin/decide` uses the door on the laptop | Given no hosted configuration of its own on the laptop, When `bin/decide` runs, Then it asks through the door |
| `bin/decide` in the cloud is unchanged | Given a cloud session with hosted configuration, When `bin/decide` runs, Then it calls the hosted model directly |
| The door restarts itself | Given the door crashes, When the laptop is left alone, Then the door is serving again without a human |
| Status says why it is down | Given the door not serving, When the owner asks for its status, Then it says why |

---

## State Machine

The door as a caller sees it.

```
             setup done, started
 +---------+ ------------------> +---------+
 |  DOWN   |                     | SERVING |
 +---------+ <------------------ +---------+
      ^         stops / crashes       |
      |                               | the credential or the hosted
      |      restarts, upstream ok    v service refuses every request
      +-------------------------- +---------+
          stops / crashes         | REFUSED |
                                  +---------+
```

| State | Condition | A request gets |
|---|---|---|
| DOWN | The door is not running, or not set up | unavailable, within the down bound |
| SERVING | The door is running | decided, or a per-request failure |
| REFUSED | The door is running and the hosted service refuses its credential | refused upstream for hosted names |

| From | To | Trigger | Condition |
|---|---|---|---|
| DOWN | SERVING | The door starts | Setup has seeded the credential |
| SERVING | REFUSED | The hosted service refuses the credential | Revoked, expired or spend cap reached |
| REFUSED | SERVING | The hosted service accepts it again | Re-seeded, or the cap resets |
| SERVING | DOWN | The door stops or crashes | It restarts on its own (G10) |
| REFUSED | DOWN | The door stops or crashes | -- |

---

## Domain Language

- **Door.** The one place on the laptop where local tools ask for
  decisions. Invariant: reachable from the laptop only.
- **Tool.** A local program that asks the door a decision request.
  Invariant: holds no hosted credential for this purpose.
- **Decision request.** A state, its questions, optional images, and the
  model name, in the public decision contract.
- **Decision.** For each question, the probability of each allowed
  option, and the name of the model that produced it.
- **Model name.** The catalog's name for one model. Invariant: one name,
  one model.
- **Catalog.** The models the door serves and where each one lives.
  Invariant: changed only in the door's configuration.
- **Backend.** Where a catalog model is answered: hosted or local.
- **Hosted credential.** The secret the door presents to the hosted
  service. Invariant: never leaves the door.
- **Answer.** The outcome of one request: decided, rejected, unknown
  model, unavailable, refused upstream or timed out.

---

## Parameters

| Bound | Constraint |
|---|---|
| Request bound | Ends every request; shorter than the default timeout of `bin/decide`, so the door answers before its own callers give up |
| Down bound | How soon a caller learns the door is not serving; short enough for a git hook to decide without stalling a commit |
| Size bound | The largest request the door accepts; large enough for the page-scan requests the ocrinator sends |
| Catalog | The set of model names; at the MVP, exactly the hosted models `bin/decide` already serves |
| Body logging upstream | Off unless the owner turns it on |

---

## Security Considerations

- **A local process spends the hosted budget.** Any process on the laptop
  can ask. The hosted spend cap bounds the damage; the door adds no
  authentication, by Non-Goal.
- **A web page is also on the laptop.** A page can send requests to a
  loopback address. The door must refuse anything a web page can send,
  including through DNS rebinding (G7).
- **The credential is the prize.** The door must never reveal it, and
  must not forward a credential supplied by a caller in its place.
- **States leave the laptop for hosted models.** Page scans and text go to
  the hosted service, as they do through `bin/decide` today. Body logging
  there stays off by default (G11).
- **A refused or exhausted credential.** The door reports refused
  upstream; it never retries in a loop that would spend more.

---

## Ships where

The owner's laptop, as an LMDE component. Not cloud sessions.

---

## Key Decisions

| Decision | Choice | Rationale | Origin |
|---|---|---|---|
| One door for local tools | A single place on the laptop, speaking the public decision contract | Tools stop carrying model plumbing and credentials | Todd, 2026-10-16: "I'm convinced" (concept) |
| Where the door lives | A tenant of the LMDE proxy layer | Every laptop service facing local callers sits behind that layer | Concept; LMDE (Todd, 2026-10-02) |
| How a backend is chosen | By the model name the request carries | The choice is explicit and needs no tool to know where models live | Concept |
| Substitution | Never | Two models' probabilities are not interchangeable | Concept |
| Credential | Held by the door, seeded once | Tools need neither a credential nor an unlocked 1Password | Concept |
| Cloud sessions | Unchanged | No LMDE there | Concept |
| First backend | Hosted | It exists today; the local backend is a later design | Concept |

---

## Open Questions

- **Q1 The name.** "Decide route" is the working name. Confirm it or
  choose another.
- **Q2 Which credential.** Reuse the laptop's existing hosted item that
  `bin/decide` reads today, or mint a dedicated one for the door in
  tds-internal, so it can be revoked alone? Recommended: dedicated.
- **Q3 Per-tool spend.** Should hosted spend through the door be
  attributed per tool, as `bin/decide` does with its tool tag, or to the
  door as one consumer?
- **Q4 "Whichever is available."** Left open by the concept. Not in the
  MVP; it would need an explicit name that callers opt into.

---

## Rejections

- **Each tool holds its own credential (today).** Every tool repeats the
  plumbing and fails when 1Password is locked.
- **Silent fallback between hosted and local.** Breaks a caller's
  thresholds without telling it.
- **A door reachable off the laptop.** Turns the hosted budget into a
  public service.
- **Cloud sessions through the door.** There is no LMDE in a cloud
  session.

---

## Future Considerations

- **The local backend.** The decision arena, as a catalog entry with its
  own design, including the caller ordering it needs.
- **Per-tool attribution** of hosted spend (Q3).
- **Opt-in "whichever is available"** (Q4).
- **Metrics** in the LMDE observability stack: requests and answers by
  kind and by model.

---

## Related Documents

- [concept: decide-route](../concepts/decide-route/CONCEPT.md) -- origin
  (non-binding).
- [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md) -- defines the LMDE proxy
  layer, Deadline proxy.
- `docs/arch/proxy-layer/ARCHITECTURE.md` -- the layer as deployed.
- `docs/ops/decide.md` -- `bin/decide`, the first caller.
- [concept: decision-arena](../concepts/decision-arena/CONCEPT.md) -- the
  later local backend.
- The `decision-models` skill -- when to reach for a decision model at
  all.
