# Design Document Style Guide

> **Purpose:** Ensure design docs are useful to both AI coding agents and human engineers.

---

## Audience

**Primary:** AI coding agents (Claude, Gemini, Copilot) who will implement the design.  
**Secondary:** Human engineers who review, maintain, and extend the implementation.

This means: be explicit, unambiguous, and testable. Avoid prose that sounds good but can't be implemented.

---

## When to Write a Design Doc

Write a design doc when:
- Building a new system or major feature
- Making architectural changes that affect multiple components
- The implementation path isn't obvious from a ticket title

An existing design doc suffices when:
- It's a bug fix or minor enhancement inside an already-designed component
- The change is fully described in a GitHub issue
- You'd spend more time documenting than implementing

**This is not a skip of the design phase.** Phase 2 never elides: you still
read the design record governing the component and confirm the change
conforms to it. What these cases skip is *authoring a new doc*. If no
design record governs the component at all, write one.

---

## Required Sections

Every design doc must have, in this order -- `TEMPLATE.md` is the
authoritative skeleton and this table must agree with it:

| Section | Purpose |
|---------|---------|
| **Header block** | Status, date, authors, dependencies |
| **Overview** | 2-3 sentences. What is this? Why does it exist? |
| **Goals** | What success looks like. Testable criteria. |
| **Non-Goals** | What this explicitly won't do. Prevents scope creep. |
| **Architecture Overview** | ASCII diagram: components, data flow, dependency direction |
| **Design** | The meat, broken into subsystems with responsibilities and interfaces |
| **State Machine** | Diagram *and* transition table, for any system with lifecycle states |
| **Data Model** | Tables, fields, relationships, constraints |
| **Data Warehouse** | What this system ledgers, or "Nothing is ledgered" with a reason |
| **Security Considerations** | Auth, secrets, attack surface, mitigations |
| **Key Decisions** | Table of decisions with rationale. Append-only after approval. |
| **Open Questions** | Unresolved issues. Honest about what's unknown. |
| **Rejections** | Alternatives considered and dismissed, one line of reasoning each |
| **Future Considerations** | Explicitly deferred work |
| **Related Documents** | Links to other design docs |

**Rejections is not optional and is not Non-Goals.** Non-Goals bounds
scope; Key Decisions records what was chosen; Rejections records what was
*not* chosen and why, so a future reader does not relitigate a settled
decision. It is the section most often missing and the one that saves the
most time later.

A section with nothing to say says so in one line ("No lifecycle states.")
rather than being dropped -- an absent section reads as an oversight, and a
reviewer cannot tell the difference.

---

## What Belongs In a Design Doc

A design doc states **what** the system does and **why**. It is not the only
document in the loop, and the others are not lesser -- they simply evolve on
different clocks. Putting content in the wrong one is not a tidiness problem;
it destroys the property that makes each artifact worth reading.

| Artifact | Answers | Evolves |
|---|---|---|
| `docs/design/` | what we intend, and why | authored once, **body frozen at APPROVED**; only status and the append-only Key Decisions log move |
| `docs/arch/` | what is deployed right now | **living**, rewritten at every release; never contains anything unshipped |
| tests | what the code must do, executably | **per behavior**, RED before GREEN, one commit at a time |
| source | how it actually does it | **continuously**, freely, within the design's guarantees |

The design freezes so drift is visible. The as-built lives so it stays true.
Tests and source iterate because that is where the work happens. A design doc
that absorbs test detail or implementation detail freezes something that
needed to keep moving -- and every later change to it either violates the
freeze or silently makes the doc a lie.

### The load-bearing test

**HOW belongs in a design doc only when it is load-bearing** -- when the
specific approach is required for a security, correctness, or performance
guarantee the design makes.

> Ask: *if an implementer chose a different approach that achieves the same
> guarantee, would the design be wrong?*
>
> Yes -> include it. No -> leave it out.

| Detail | Include? | Why |
|---|---|---|
| "Tokens are stored as SHA-256 hashes" | yes | security: prevents replay if the store leaks |
| "SERIALIZABLE isolation on consume" | yes | correctness: prevents double-consumption |
| "Cursor-based pagination" | yes | correctness: stable results under concurrent writes |
| "Retry 3x at 50ms/100ms/200ms, 25% jitter" | no | any reasonable backoff satisfies the design |
| "Redis-backed sliding window" | no | any rate limiter satisfies the design |
| "Uses `json-stable-stringify`" | no | any deterministic serializer satisfies the design |

An RPC protocol design is a worked example of the boundary. The design must
pin down whatever the rest of the system's correctness rests on -- the
transport guarantee, the identity and versioning of the contract, what
happens on partial failure, which errors are retryable. It must not
enumerate endpoints, field-by-field payload shapes, status-code tables, or
serializer choices. Those are the implementation's business, and pinning
them in a frozen document means the first schema change either breaks the
freeze or leaves the doc lying.

**Be explicit *about the right things*.** "Be Explicit" below and this
section are not in tension: vagueness about a guarantee is a defect, and
precision about a non-load-bearing mechanism is scope creep. "Handle errors
gracefully" fails because no implementer can satisfy or violate it. "Retry
at 50ms/100ms/200ms with 25% jitter" fails because any implementer could
satisfy the real requirement differently. The target is between them: name
the guarantee, in terms that can be verified.

### Where displaced content goes

Content cut from a design doc is not deleted -- it is routed:

| Content | Home |
|---|---|
| Test cases, coverage targets, fixtures | the test suite; the `testing` skill |
| Build order, phases, task breakdown | root `TODO_PLAN.md`; the `planning` skill |
| Deploy steps, dashboards, on-call, runbooks | `docs/arch/` or a runbook; the `release` skill |
| Timing values, library choices, algorithms | the code, and its comments |
| What actually shipped | `docs/arch/`, at release; the `architecture` skill |

Reference the home ("see [X]"); do not inline it.

---

## Architecture Expectations

The fleet builds layered, abstract, composable systems. Clean Architecture,
Hexagonal (Ports & Adapters), and Domain-Driven Design are three angles on
one idea, not three checklists: **separate what the software means from how
it connects to the world, and point every dependency inward.** The `coding`
skill is the authority on realizing this in code. A design doc's job is to
commit to it on paper, before there is code to check.

A design doc demonstrates the architecture by answering four things:

| Question | Where it lands | Failure to answer |
|---|---|---|
| What is the **core** -- the decisions and rules in the problem's own language? | Design / Architecture Overview | the doc describes a pipeline of mechanisms with no meaning at the middle |
| What is **likely to change** -- vendors, wire formats, storage, model ids, hosts? | Design, and one Key Decisions row per axis | a mechanism is load-bearing and nobody noticed |
| Which **one seam** carries each axis of change -- a port, a policy, or a parameter? | Design; the seam is named | the mechanism is hardcoded, and swapping it is a rewrite |
| Which way do **dependencies point**? | Architecture Overview diagram | an inverted dependency ships and is found in code review, or later |

Two rules govern the answers:

- **No vendor or mechanism name in the core.** An SDK, an env var, a wire
  format, or a model id belongs at an edge. If the doc puts one in the
  middle, say so explicitly and move it.
- **Do not over-seam (YAGNI).** A port earns its place when there are, or
  plausibly will be, two implementations, or when it crosses a vendor or
  process boundary. A single-implementation-forever port is ceremony; if it
  was considered and dropped, that belongs in Rejections.

A good Key Decisions row often *is* an axis of change plus the seam chosen
for it -- "LLM vendor -> `CompletionPort`, model id supplied at the edge."

**A design doc with no named seams is not finished and must not be
approved.** The freeze would make the seams unwritable, and a seam first
discovered while coding was never reviewed -- that is drift by definition.
Naming them is phase 3; the `architecture` skill is its authority, and its
output lands in this document before approval.

---

## Writing Style

### Be Explicit
```
BAD:  "The system should handle errors gracefully"
GOOD: "On HTTP 5xx, retry 3 times with exponential backoff (1s, 5s, 25s), then fail the operation"
```

### Be Testable
```
BAD:  "Fast response times"
GOOD: "P95 latency under 500ms for batch sizes <= 20"
```

### Be Unambiguous
```
BAD:  "The agent processes the request"
GOOD: "The CLI agent (Claude Code, Gemini CLI, or Amp) processes the request"
```

### Prefer Tables Over Prose
Tables are scannable. Prose buries information.

```
BAD:  "The system can be in one of several states. When it starts, it's in the OPEN 
      state. From there it can move to SEALED when the user confirms, or to 
      CANCELLED if they abort..."

GOOD: | From | To | Trigger |
      |------|-----|---------|
      | OPEN | SEALED | User confirms |
      | OPEN | CANCELLED | User aborts |
```

### Use ASCII Diagrams
Mermaid is fine for human readers, but ASCII diagrams work everywhere -- including in prompts to AI agents.

```
+--------------+     +--------------+     +--------------+
| Component A  |---->| Component B  |---->| Component C  |
+--------------+     +--------------+     +--------------+
```

---

## State Machines

Any system with lifecycle states **must** include a state machine diagram and transition table.

```
+-----------+         +-----------+
|   OPEN    |-------->|  SEALED   |
+-----------+         +-----------+
```

| From | To | Trigger | Condition |
|------|-----|---------|-----------|
| OPEN | SEALED | `seal` command | Always allowed |

---

## Key Decisions Table

Every design doc must have a Key Decisions section. Format:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Database | PostgreSQL | Team expertise, integration requirements |
| Auth | RLS | Row-level security built-in |

This table is gold for future readers (human or AI) who ask "why was it done this way?"

---

## File Naming

| Pattern | Use For |
|---------|---------|
| `DESIGN.<name>.md` | Feature or component design |
| `INTEGRATION.md` | How components connect |
| `NEW.<name>.md` | Supersedes an older doc (keep old for history) |

All caps for the type **prefix** -- the leading token before the first
dot (`DESIGN`, `INTEGRATION`, `NEW`). The `<name>` that follows is also
all caps, kebab-cased when it is more than one word:
`DESIGN.CI-MAGIC-CONFIDENCE.md`, `DESIGN.DESIGNOMATIC-SELF-SERVE.md`.

**As-built documentation is not a design doc** and does not live in this
tree. `docs/design/` is aspirational and freezes at APPROVED; `docs/arch/`
is factual and living, describing only what is deployed. See
`docs/arch/README.md` and the `architecture` skill.

---

## Status Vocabulary

Use exactly one of:

| Status | Meaning |
|--------|---------|
| `DRAFT` | Work in progress, not ready for implementation |
| `REVIEW` | Ready for human review |
| `APPROVED` | Reviewed and approved, ready to implement |
| `IMPLEMENTED` | Design is in production |
| `SUPERSEDED` | Replaced by another doc (link to it) |

---

## Header Block Template

```markdown
# Title

> **Status:** DRAFT  
> **Date:** YYYY-MM-DD  
> **Authors:** Names  
> **Depends on:** [Other Doc](./path.md) (if applicable)
```

---

## Anti-Patterns

- **Wall of text** -- Break it up with headers, tables, diagrams
- **Vague goals** -- "Improve performance" means nothing
- **Missing non-goals** -- Scope creep happens when boundaries aren't explicit
- **No key decisions** -- Future readers will guess wrong
- **Rewriting the doc to match the code** -- When the implementation
  diverges, cut a drift issue. Editing the frozen record destroys the only
  artifact that could show the drift, and launders an unreviewed decision
  into apparent spec. Only a human amends an approved record
- **Implementation detail in a frozen document** -- see the load-bearing
  test above; it is the most common way a design doc becomes a lie
- **No named seams** -- a design that does not say what is likely to change
  has not been architected, only described
