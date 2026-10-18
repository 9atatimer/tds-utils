# Decide Route

> **Status:** DRAFT  
> **Date:** 2026-10-16 (panel findings folded in 2026-10-18; second panel folded in 2026-10-18)  
> **Authors:** Todd Stumpf, Claude  
> **Depends on:** [LMDE](./LMDE.DESIGN.md); the LMDE proxy layer as defined in [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md), Deadline proxy  
> **Origin:** [concept: decide-route](../concepts/decide-route/CONCEPT.md), Issue#382

---

## Overview

The decide route is the one place on the laptop where local tools ask
decision questions. A tool names a model and sends its questions. The
route answers from that model, hosted or local, and the tool never holds
a credential. In this record the route is called the door.

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
  so a client changes its address, and at most the model name it asks for.
- The model a request names decides where it is answered. The door's
  catalog says which models it serves and where each one lives.
- The door holds the hosted credential. Tools hold none.
- A request is answered by the model it names or refused. The door never
  substitutes another model.

**Tradeoffs.**

| Given up | Why it is worth it |
|---|---|
| Any local process can spend the hosted budget through the door | The hosted service's existing spend caps still apply, and the door is unreachable off the laptop |
| A tool cannot ask for "whichever model is available" | Two models' probabilities are not interchangeable, so a silent switch would break a caller's thresholds |
| Cloud sessions do not use the door | They have no LMDE; they keep calling the hosted model directly, as today |
| One more always-on service on the laptop | It replaces a credential read and a configuration in every tool |
| Shared fate with the LMDE proxy layer the door depends on | The door is down whenever the layer is, and applying a change to the door may interrupt requests in flight through the layer. In exchange the door inherits supervision, laptop-only reach, a deadline and body-free logs instead of rebuilding them; an invalid door change never reaches the layer (G12) |
| A caller cannot turn on upstream body logging | Body logging is a privacy choice the owner makes once, not one any local process can make per request (G11) |
| A relay that does not say so looks like a tool | Only a process running as the owner can set one up, and it could spend through the door directly; telling tools apart would mean authenticating local callers (Non-Goals) |

---

## Goals

- **G1 One door.** A local tool sends a decision request to one address on
  the laptop and gets back, for every question, the probability of each
  allowed option.
- **G2 Existing clients work.** A client of the public decision contract
  works through the door after changing only its address and, where its
  model names differ, the name it asks for. What that contract does not
  carry -- a tool label, a body-logging choice -- the door supplies from
  its own configuration, so a plain client sends nothing beyond the
  contract. `bin/decide` already has such a client; through the door it
  sends what it sends any contract server today, plus its tool label
  where Q3 makes one count.
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
  browser on it, can get a decision from the door or spend through it.
  No tunnel or other relay is pointed at the door, and a request that
  says it was relayed onto the laptop is refused even if one someday is.
- **G8 Never hang, and say why.** Every request gets an answer within a
  bound, an offline laptop answers as promptly as a stopped door, and the
  caller can tell the kinds of failure apart, including which are worth
  retrying (Design, Answers).
- **G9 Hosted spend stays capped and visible.** Every request through the
  door counts against a hosted spend cap and appears in the hosted
  service's log. How caps are divided among tools is Q3.
- **G10 Runs unattended, visibly.** The door starts at login and restarts
  after a crash, needing no human. One command shows whether it is
  serving, each backend's last learned condition, and, when something is
  wrong, why.
- **G11 Bodies stay out of logs.** No request or response body is written
  to disk on the laptop. Hosted requests ask the hosted service not to log
  bodies unless the owner turns that on in the door's configuration; no
  caller can turn it on.
- **G12 A bad change hurts nothing.** A change to the door's
  configuration is checked before it takes effect. An invalid one is
  refused and leaves the running door, and every other service the proxy
  layer carries, as they were.
- **G13 The credential is worth little elsewhere.** The door's copy of
  the hosted credential is readable only by the door, can be revoked
  alone, and spends on decision models only. G13 stands or falls with Q2.

---

## Non-Goals

- **A local model in the MVP.** The decision arena joins later as a
  catalog entry, with its own design (concept: decision-arena).
- **Ordering callers.** A queue that puts git hooks ahead of batch work
  belongs to the local backend, which is the only one with a single
  scarce GPU.
- **Callers off the laptop.** No tunnel, now or in this design.
- **Cloud sessions.** They keep calling the hosted model directly.
- **Authenticating local callers.** Any process running as the owner is
  trusted to ask. The door checks where a request came from -- a tool on
  the laptop, not a web page, not a relay that says so -- and never which
  tool sent it.
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
| Checked before forwarded | Every refusal the door can make on its own -- malformed, oversized, unknown model, not from a tool on the laptop, an image by address -- is made before any backend sees the request, so a refused request never costs money |
| Images inline only | An image travels inside the request. A request that names an image by address is rejected; neither the door nor any backend fetches anything on a request's behalf |
| One attempt | The door sends a request to its backend at most once. Retrying is the caller's choice, guided by the answer's kind, so the door never spends twice on one request |

Where the door runs within LMDE is the architecture record's
(`ARCHITECTURE.decide-route.md`); this record fixes only the dependency on
the proxy layer and the capabilities in G7, G8, G10, G11 and G12.

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
| Readers | The door can read the plaintext without a human present. No other user can read it, and it is in no plain file, no checkout, and no backup of either |
| Read unattended | Reading it never raises a prompt a human must answer; if it cannot be read without one, the hosted backend is not set up and status says so |
| Re-seeded in place | Rotation is the same one-step seed; the door uses the new copy without anything else being reinstalled |
| Worth little elsewhere | Dedicated to the door, revocable alone, and able to spend on decision models only (G13, Q2) |
| Never shown | It never appears in an answer, a log, a status output or a process listing, including when a backend's reply echoes the request |
| Callers cannot override it | A credential a caller sends is never forwarded |

### Answers

Every request ends in exactly one of these. A caller can tell them apart
without reading prose, and each says whether the fault is the request's,
the door's, or the backend's.

The kinds ride in the public decision contract's existing error shape; the
door adds no new shape. Where the door cannot answer at all -- not serving,
or gone mid-request -- the caller learns the kind from the failed
connection itself, so a plain client sees it as an ordinary connection
failure.

| Answer | When | Whose | Retry? | The caller should |
|---|---|---|---|---|
| decided | The named model answered with a complete decision | -- | -- | use it |
| rejected | The request is malformed, too large, names an image by address, or is not from a tool on the laptop (a web page, a request that says it was relayed) | request | never unchanged | fix the request |
| unknown model | The name is not in the catalog | request | never unchanged | fix the name |
| not set up | The name is in the catalog, but the door's own setup for its backend is missing or unreadable (no credential seeded, a credential that cannot be read unattended) | door | not until a human fixes the door | stop; status names what is missing |
| unavailable | The door is not serving and refused the connection; or the named model's backend cannot be reached within the reach bound, is temporarily out of capacity, or is turning away requests that arrive too fast | door or backend | yes, later; when the backend said how long to wait, the answer says so | retry later, more slowly, or stop; never switch models |
| interrupted | The door accepted the request, then stopped before answering: a crash, a restart, or a configuration change applied | door | with care: the backend may have answered, and charged | retry at most once, or stop |
| credential refused | The hosted service refused the door's credential | backend | no | stop; a human must re-seed or re-grant it |
| spend capped | The hosted service refused because a spend cap is reached | backend | not until the cap's window resets; the answer says when, if the service said | stop or wait; never switch models |
| unreadable | The backend answered, but not with a complete decision | backend | not unchanged | report it; the answer carries what came back, never the credential |
| timed out | No answer within the request bound | backend | with care: the backend may have answered, and charged, after the door gave up | retry at most once, or stop |

Retrying is always the caller's; the door makes one attempt (The door).

### Callers

| Caller | Rule |
|---|---|
| `bin/decide` on the laptop | Asks through the door when no hosted configuration of its own is set. Its per-call body-logging switch does not reach the door (G11); its tool label does, where Q3 makes one count |
| `bin/decide` in a cloud session | Unchanged: calls the hosted model directly |
| Any other local tool | Speaks the public decision contract to the door's address, and may add a tool label |
| A tool label | A name, not a credential: it attributes spend and selects nothing. A request without one is the door's own |

---

## Behaviors

| Behavior | Given / When / Then |
|---|---|
| A tool gets a hosted decision | Given the door serving and a catalog hosted model, When a tool sends a request naming it with a choice and a yes/no question, Then the answer is decided and holds every option's probability for both |
| A plain contract client works | Given a client of the public decision contract that sends nothing beyond it, When it is pointed at the door and names a catalog model, Then the answer is decided |
| The answer names its model | Given any decided answer, When the tool reads it, Then it names the catalog model that produced it |
| No credential needed | Given a tool that sends no credential, When it asks, Then it is answered |
| A locked 1Password does not matter | Given 1Password locked after setup, When a tool asks a hosted model, Then it is answered |
| A caller's credential is not forwarded | Given a request carrying its own credential, When the door forwards it, Then the hosted service sees the door's credential only |
| An unknown model is refused | Given a name not in the catalog, When a tool asks, Then the answer is unknown model and nothing is sent to any backend |
| A door not set up says so | Given a catalog hosted model and no seeded credential, When a tool asks for it, Then the answer is not set up, nothing is sent, and status names the missing credential |
| An unavailable model is not substituted | Given a catalog model whose backend cannot be reached, When a tool asks for it, Then the answer is unavailable and no other model answers |
| An offline laptop answers promptly | Given the laptop offline, When a tool asks a hosted model, Then the answer is unavailable within the reach bound |
| The credential is refused | Given the hosted service refusing the door's credential, When a tool asks, Then the answer is credential refused |
| The spend cap is reached | Given a hosted spend cap reached, When a tool asks, Then the answer is spend capped, and says when the cap resets if the service said |
| A capacity refusal is retryable | Given the hosted model temporarily out of capacity, When a tool asks, Then the answer is unavailable and marked worth retrying later |
| An unreadable answer is not a decision | Given a backend that answers without a probability for every option of every question, When a tool asks, Then the answer is unreadable, never decided |
| The door tries once | Given any request that fails at its backend, When the door answers, Then the backend saw it at most once |
| A slow answer is cut off | Given a backend that does not answer within the request bound, When a tool asks, Then the answer is timed out within the bound |
| A stopped door says so at once | Given the door not serving, When a tool asks, Then the tool learns unavailable within the down bound |
| A crash mid-request is interrupted | Given a request the door has accepted, When the door crashes before answering, Then the tool learns interrupted, never decided, and never unavailable |
| A change mid-request is interrupted | Given a request in flight, When a valid door configuration is applied, Then the tool learns either the answer or interrupted |
| A malformed request is rejected | Given a request that is not a valid decision request, When it is sent, Then the answer is rejected and no backend sees it |
| An oversized request is rejected | Given a request over the size bound, When it is sent, Then the answer is rejected and no backend sees it |
| An image by address is rejected | Given a request naming an image by address instead of carrying it, When it is sent, Then the answer is rejected, no backend sees it, and nothing fetches the address |
| Images pass through | Given a request carrying images inline, When a hosted model that reads images is named, Then the images reach it unchanged |
| A web page cannot spend | Given a request a web page in a browser on the laptop can send without the browser asking first, When it reaches the door, Then it is rejected and no backend sees it |
| A web page cannot read an answer | Given a web page in a browser on the laptop, When it sends any request to the door, Then the page cannot read the answer |
| A rebound name cannot reach the door | Given a web page whose own name has been made to point at the laptop, When it sends a request to the door, Then it is rejected and no backend sees it |
| Nothing off the laptop can ask | Given a host other than the laptop, When it tries to reach the door, Then it gets no decision |
| A relayed request is refused | Given a request relayed onto the laptop from off it that says it was relayed, When it reaches the door, Then it is rejected and no backend sees it |
| Bodies are not logged | Given any request, When it completes or fails, Then no body is on the laptop's disk |
| A caller cannot turn on body logging | Given a request asking for its body to be logged upstream, When the door forwards it, Then the hosted service is asked not to log bodies, unless the owner turned it on |
| Hosted spend is capped | Given door traffic, When it reaches the hosted service, Then it counts against a hosted spend cap and appears in its log |
| A tool label is not a credential | Given a request carrying a tool label, When the door forwards it, Then it is answered exactly as without one, except for how its spend is attributed and capped |
| A new catalog entry needs no tool change | Given a model added to the catalog, When a tool names it, Then it is answered with no change to the tool |
| An invalid change leaves everything running | Given the door and another proxy-layer service serving, When an invalid door configuration is applied, Then it is refused, and both keep serving as before |
| The credential is not readable as a file | Given the door set up, When the laptop's files are searched for the credential, Then it is found in no plain file |
| The credential is never shown | Given the door set up and a backend whose reply echoes the request, When the owner reads that answer, the door's logs, its status and the process listing, Then the credential appears in none of them |
| Re-seeding rotates the credential | Given a new hosted credential, When the owner re-seeds the door, Then the next request uses it with nothing reinstalled |
| `bin/decide` uses the door on the laptop | Given no hosted configuration of its own on the laptop, When `bin/decide` runs, Then it asks through the door |
| `bin/decide` in the cloud is unchanged | Given a cloud session with hosted configuration, When `bin/decide` runs, Then it calls the hosted model directly |
| The door restarts itself | Given the door crashes, When the laptop is left alone, Then the door is serving again without a human |
| Status says why it is down | Given the door not serving, or a backend not ready, When the owner asks for its status, Then it says which and why |
| Status before any request | Given a backend no tool has asked since the door started, When the owner asks for status, Then it reports not set up if the door's setup is missing, and otherwise that the condition is not yet learned |

---

## State Machine

The door and each backend behind it each have a condition, as a caller
sees them. A backend's condition matters only while the door is serving.
Splitting them keeps a fault in the door's own setup apart from a refusal
by the hosted service, and lets a later local backend serve while the
hosted one cannot.

### The door's condition

```
             setup checked, started
 +---------+ ---------------------> +---------+
 |  DOWN   |                        | SERVING |
 +---------+ <--------------------- +---------+
                 stops / crashes
```

| Condition | Meaning | A request gets |
|---|---|---|
| DOWN | The door is not running | unavailable, within the down bound |
| SERVING | The door is running | whatever its backend's condition gives |

| From | To | Trigger | Condition |
|---|---|---|---|
| DOWN | SERVING | The door starts | Its configuration is valid (G12) |
| SERVING | DOWN | The door stops or crashes | Requests in flight are interrupted; it restarts on its own (G10) |
| SERVING | SERVING | A valid configuration change is applied | Requests in flight may be interrupted |

### A backend's condition

```
                         +------------+
                         | NOT SET UP |
                         +------------+
                     seeded  |      ^  seed lost (from any condition)
                             v      |
 +------------+  refused   +---------+  cap reached   +--------+
 | CREDENTIAL | <--------- |  READY  | -------------> | CAPPED |
 |  REFUSED   | ---------> |         | <------------- |        |
 +------------+ re-seeded  +---------+  window resets +--------+
                             |      ^
                 not reached v      | reached again
                         +-------------+
                         | UNREACHABLE |
                         +-------------+
```

| Condition | Meaning | A request naming one of its models gets |
|---|---|---|
| NOT SET UP | The door's own setup for this backend is missing or cannot be read unattended | not set up; nothing is sent |
| READY | The backend answers | decided, or a per-request failure (rejected, unreadable, timed out) |
| UNREACHABLE | The backend cannot be reached within the reach bound, or is out of capacity | unavailable |
| CREDENTIAL REFUSED | The hosted service refuses the door's credential | credential refused |
| CAPPED | A hosted spend cap is reached | spend capped |

| From | To | Trigger | Condition |
|---|---|---|---|
| NOT SET UP | READY | A human seeds the credential | -- |
| any other condition | NOT SET UP | The seeded copy is removed or becomes unreadable | -- |
| READY | UNREACHABLE | A request cannot reach the backend | Offline, or out of capacity |
| UNREACHABLE | READY | A request reaches it again | -- |
| READY | CREDENTIAL REFUSED | The hosted service refuses the credential | Revoked or expired |
| CREDENTIAL REFUSED | READY | A human re-seeds or re-grants it | -- |
| READY | CAPPED | The hosted service refuses for spend | A cap is reached |
| CAPPED | READY | The cap's window resets | -- |

A backend's condition is learned from requests, not probed: the door
sends nothing to a backend that no tool asked for. NOT SET UP is the
exception, because it is the door's own setup and the door knows it
without a request. Until a request teaches it otherwise, status reports
any other backend as not yet learned. CAPPED holds per cap: for the whole
backend under one cap, or per tool label under per-tool caps (Q3).

## Domain Language

- **Door.** The one place on the laptop where local tools ask for
  decisions. Invariant: reachable from tools on the laptop only.
- **Owner.** The human whose laptop runs the door. Invariant: the only
  one who seeds the credential or changes the door's configuration.
- **Tool.** A local program that asks the door a decision request.
  Invariant: holds no hosted credential for this purpose.
- **Tool label.** A name a tool may attach to its request so spend is
  attributed to it. Invariant: grants nothing and selects nothing.
- **Public decision contract.** The published request and answer shape
  that decision clients already speak. Invariant: the door changes
  neither shape.
- **Decision request.** A state, its questions, optional inline images,
  and the model name, in the public decision contract.
- **State.** What the questions are asked about, as the contract carries
  it. Distinct from the door's and a backend's condition.
- **Question.** One thing a decision request asks, with its allowed
  options.
- **Option.** One allowed answer to a question. Invariant: a decision
  gives every option a probability.
- **Decision.** For each question, the probability of each allowed
  option, and the name of the model that produced it.
- **Model name.** The catalog's name for one model. Invariant: one name,
  one model.
- **Catalog.** The models the door serves and where each one lives.
  Invariant: changed only in the door's configuration.
- **Backend.** Where a catalog model is answered: hosted or local. Has a
  condition: not set up, ready, unreachable, credential refused or
  capped.
- **Hosted credential.** The secret the door presents to the hosted
  service. Invariant: never leaves the door.
- **Seed.** A human copying the hosted credential from 1Password into the
  door. Invariant: the only step that needs 1Password unlocked.
- **Answer.** The outcome of one request: decided, rejected, unknown
  model, not set up, unavailable, interrupted, credential refused, spend
  capped, unreadable or timed out.
- **Status.** The owner's view of the door: whether it is serving, each
  backend's last learned condition, and why when something is wrong.
  Invariant: never shows the credential.

---

## Parameters

| Bound | Constraint |
|---|---|
| Request bound | Ends every request; shorter than the default timeout of `bin/decide`, so the door answers before its own callers give up |
| Reach bound | How long the door tries to reach a backend before answering unavailable; longer than a slow but working connection to the hosted service takes, and short enough that an offline laptop answers a git hook without stalling a commit |
| Down bound | How soon a caller learns the door is not serving; short enough for a git hook to decide without stalling a commit |
| Size bound | The largest request the door accepts; large enough for the page-scan requests the ocrinator sends |
| Catalog | The set of model names; at the MVP, exactly the hosted models `bin/decide` already serves |
| Body logging upstream | Off unless the owner turns it on in the door's configuration; never per request |
| Refusal classification | A rule mapping each hosted refusal to an answer kind (unavailable and retryable, credential refused, spend capped, unreadable); retuned without adding or removing an answer kind |
| Spend attribution | A rule for which cap a request counts against; per Q3, and never chosen by a caller beyond its tool label |

---

## Security Considerations

- **A local process spends the hosted budget.** Any process on the laptop
  can ask. The hosted spend caps bound the damage; the door adds no
  authentication, by Non-Goal. A tool label is not a credential, so a
  process can spend under another tool's label; under per-tool caps (Q3)
  that exhausts at most that tool's cap.
- **A web page is also on the laptop.** A page can send requests to a
  loopback address, and some it can send without the browser asking the
  door first. The door must refuse anything a web page can send before
  any backend sees it, including through DNS rebinding, and must never let
  a page read an answer (G7). Refusing after forwarding is not enough: the
  hosted service has already charged.
- **A relay brings off-laptop traffic onto the laptop.** A tunnel or any
  local forwarder makes a remote request look local. No tunnel names the
  door as its origin, and a request that says it was relayed is refused
  (G7). A relay that says nothing looks like a tool. Only a process
  running as the owner can set one up, and that process could already
  spend through the door itself, so the door does not try to tell them
  apart (Non-Goals, Tradeoffs).
- **The credential is the prize.** The door must never reveal it,
  including through status, logs, or a backend reply that echoes the
  request, and must not forward a credential supplied by a caller in its
  place. No other user can read it, and it is in no plain file (G13). A
  process running as the owner may be able to read it; any such process
  can already spend through the door, so what a stolen copy adds is use
  from off the laptop. Being dedicated, revocable alone and limited to
  decision models is what bounds that (Q2).
- **Images by address are a fetch on someone's behalf.** A hosted or local
  backend that fetches an image address turns a request into a request
  to a third host, from a different place, and can carry data out in the
  address. The door rejects them (The door); the local backend's own
  fetching is hardened separately (Issue#401).
- **States leave the laptop for hosted models.** Page scans and text go to
  the hosted service, as they do through `bin/decide` today. Body logging
  there stays off by default, and only the owner can turn it on (G11).
- **A refused or exhausted credential.** The door answers credential
  refused or spend capped, makes one attempt per request, and never
  retries in a loop that would spend more.
- **An interrupted request may have been charged.** The answer
  interrupted says so, and the caller retries at most once.
- **Shared fate.** The door depends on the LMDE proxy layer. A door change
  is checked before it takes effect, so a bad one cannot stop the layer or
  its other services (G12).

---

## Ships where

One stage: the owner's laptop, as an LMDE component, on the platforms
LMDE supports. No nonprod stage; the runbook names the stand-in or says
none. Not cloud sessions.

---

## Key Decisions

| Decision | Choice | Rationale | Origin |
|---|---|---|---|
| One door for local tools | A single place on the laptop, speaking the public decision contract | Tools stop carrying model plumbing and credentials | Todd, 2026-10-16: "I'm convinced" (concept) |
| What the door depends on | The LMDE proxy layer, for supervision, laptop-only reach, a deadline and body-free logs (G7, G8, G10, G11) | Rebuilding each would cost more than the shared fate, which G12 bounds. Where the door sits within the layer is the architecture record's | Concept ("the door sits with everything else that faces local services"); proxy layer per the Ollama Gateway design; placement routed out by panel, 2026-10-18 |
| How a backend is chosen | By the model name the request carries | The choice is explicit and needs no tool to know where models live | Concept |
| Substitution | Never | Two models' probabilities are not interchangeable | Concept |
| Credential | Held by the door, seeded once | Tools need neither a credential nor an unlocked 1Password | Concept |
| Cloud sessions | Unchanged | No LMDE there | Concept |
| First backend | Hosted | It exists today; the local backend is a later design | Concept |

---

## Open Questions

Q2 and Q3 must be answered before this record is APPROVED. Each names
the rows its answer changes.

- **Q1 The name.** "Decide route" is the working name. Confirm it or
  choose another.
- **Q2 Which credential.** Reuse the laptop's existing hosted item that
  `bin/decide` reads today, or mint a dedicated one for the door in
  tds-internal, so it can be revoked alone? Recommended: dedicated. Also
  confirm tds-internal can mint one limited to decision models. G13 holds
  only if it is dedicated; reusing the existing item removes G13 and the
  "Worth little elsewhere" credential rule, and weakens the Security
  bullet "The credential is the prize".
- **Q3 Per-tool spend.** Should hosted spend through the door be
  attributed and capped per tool label, as `bin/decide` is today, or
  charged to the door as one consumer under one cap? Recommended: per
  tool label, with unlabelled requests charged to the door. That keeps
  today's per-tool caps (a runaway hook cannot spend the ocrinator's
  budget) and needs nothing from a plain contract client. Either way G9
  holds. The answer changes G2, the Callers table, the Tool label
  definition, the behavior "A tool label is not a credential", the
  Spend attribution parameter, CAPPED in the backend's condition, and the
  first Security bullet.
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
- **Caller-set body logging.** Any local process, a web page's request
  included, could then have bodies kept upstream; the choice is the
  owner's, made once (G11).
- **The door retrying on a caller's behalf.** A retry the caller cannot
  see can spend twice on one request, and stacks on the caller's own
  retries.
- **Fetching images by address.** A fetch on a request's behalf is a
  side effect on a third host and a way to carry data out.

---

## Future Considerations

- **The local backend.** The decision arena, as a catalog entry with its
  own design, including the caller ordering it needs.
- **Per-tool attribution** of hosted spend, if Q3 rules the door one
  consumer for the MVP.
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
- `docs/design/ARCHITECTURE.decide-route.md` -- to be written once this
  record is APPROVED; owns the door's placement on the proxy layer and
  the seams.
- `docs/ops/decide.md` -- `bin/decide`, the first caller.
- [concept: decision-arena](../concepts/decision-arena/CONCEPT.md) -- the
  later local backend.
- The `decision-models` skill -- when to reach for a decision model at
  all.
