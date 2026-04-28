# Orchestrator Workflows -- Design Discussion Notes

> **Status:** DRAFT
> **Date:** 2026-04-16
> **Authors:** Todd Stumpf, Claude
> **Depends on:** [ORCHESTRATOR.DESIGN.md](./ORCHESTRATOR.DESIGN.md)

---

## Overview

Working notes from the design discussion on workstream orchestration and
workflow mechanics. This captures terminology alignment, workflow identification,
and initial analysis of how NATS primitives serve (but do not replace) the
workflow layer.

---

## Terminology

### Workstream

The full body of directed work the orchestrator manages. Variable in scope --
from "build me a new product" to "fix these three bugs." The orchestrator
treats them the same; only the depth of decomposition varies.

Properties:

- **Natural language in, structured work out** -- developer describes intent
  conversationally, orchestrator decomposes into tasks, agents execute
- **Human can scrub in at any level** -- not just approve/reject at the top.
  Developer can drop into a specific task's context, see what went wrong,
  intervene directly, hand it back
- **Orchestrator is the continuity** -- agents are ephemeral, developer dips
  in and out, orchestrator maintains state, context, and progress

### Workflow

The mechanistic process that advances a unit of work through its state graph.
Rigid by design -- that's the point. It's the testable contract from the
"descriptive FSM" philosophy.

"This task is in state A, condition X is met, transition to state B, emit
event Y."

### Relationship

The orchestrator manages workstreams. Workflows are the machinery inside.

- Workstream = higher-order structure owning tasks, dependencies, project
  context, and the human relationship
- Workflow = rules engine governing how individual units (tasks, reviews,
  agents) traverse their state graphs

---

## NATS Primitives: What They Are and What They Are Not

NATS provides the plumbing. It does not provide workflow logic.

| Primitive | What it is | What it is NOT |
|-----------|-----------|----------------|
| JetStream consumers | Durable message delivery with ack/nak/term | A task state machine |
| KV Store + Watch | Reactive state storage with CAS | A workflow engine |
| Subject hierarchy | Event routing topology | Business process logic |
| Headers | Message metadata | State representation |
| NATS Micro | RPC service scaffolding | An orchestration framework |

JetStream tells you whether a **message was processed**. It does not tell you
whether a **task moved through a business workflow**. Those are completely
different concerns.

### What NATS gives us for building workflows

- **JetStream**: durable event transport with at-least-once delivery, retry
  budgets (MaxDeliver), and dead-letter advisories
- **KV Watch + CAS**: reactive state management -- watch state keys, CAS
  ensures transitions are conflict-free, history provides audit trail
- **Subject hierarchy**: `PROJECT.<id>.task.<task-id>.state.changed` -- the
  routing IS the topology, no router service needed
- **Advisories**: system-level events (no responders, max deliveries exceeded)
  that the Event Supervisor can act on

### What we build on top

The **workflow layer** -- the states, transitions, conditions, dependency
resolution, quality gates, escalation, compensation. This is application code
(or configuration-driven logic) that:

1. Reads events from JetStream
2. Evaluates conditions against current state (in KV)
3. Writes new state (via CAS)
4. Emits downstream events (to JetStream)

---

## Identified Workflows

Six workflows identified. The first two form the spine -- everything else
hangs off them.

### 1. Project Inception (workstream creation)

Idea -> conversation -> project creation -> task decomposition -> tasks
available for claiming.

This is the "top of the funnel." The user story from the supplemental doc
describes this end to end. Key questions:

- How does the orchestrator decompose goals into tasks? LLM-assisted?
- How are task dependencies expressed and stored?
- When does the workstream become "active" -- after decomposition, or after
  human approval of the task graph?

### 2. Task Execution (the spine)

Task available -> claimed by agent -> agent works -> produces artifact ->
review -> done / failed / rework.

This is where the workflow FSM crystallizes. A task's states are richer than
JetStream's delivery states:

- Pending (unblocked, available for claiming)
- Blocked (waiting on dependency)
- Claimed (agent has taken it)
- In progress (agent actively working, heartbeating)
- In review (work product submitted for quality gate)
- Rework (review rejected, sent back with feedback)
- Done (accepted)
- Failed (exceeded retry budget or deemed infeasible)
- Cancelled (workstream paused or user intervention)

None of these are JetStream consumer states. These are KV-resident business
states with workflow transitions.

### 3. Review / Quality Gate

Work product evaluated against quality bar -> accepted or sent back with
feedback. May involve a different agent class than the one that produced the
work.

- Is review always a separate agent, or can some tasks self-certify?
- What does the quality bar look like concretely? Lint passes? Tests pass?
  LLM review? Human approval?
- Review failure -> rework: how much context does the reworking agent get
  about why it was rejected?

### 4. Context Sharing

Agent on project A needs knowledge from project B. Governed by
whitelist/blacklist graph.

- Triggered how? Agent requests context? Orchestrator proactively injects?
- What's the unit of shared context -- a file? A design doc? A task summary?
  A conversation transcript?

### 5. Outside Participation

Human in an IDE (Cursor, Claude Code, etc.) claims work, contributes results
back into the orchestrator's workstream.

- How does a human "register" as a participant? NATS credentials? Lighter
  interface (GitHub issue assignment)?
- How does the orchestrator track progress of work it doesn't control?
- Does the human's work product go through the same review workflow?

### 6. Monitoring / Intervention

User checks status, reprioritizes, pauses, cancels, reassigns.

- Status queries: read from KV, present via CLI
- Reprioritization: update KV, downstream consumers see new priority
- Pause: workflow transition that freezes all pending/available tasks
- Cancel: workflow transition with compensation (clean up in-flight work)

---

## Open Design Thread: Where Does Workflow Logic Live?

Three options, not yet decided:

**A. Dedicated workflow service** -- a control-plane component that subscribes
to state-change events, evaluates transition rules, and writes new state.
Central, testable, but risks becoming a god-process.

**B. Distributed in consumers** -- each agent/service knows its own transition
rules. The coding agent knows that when it finishes, the task goes to "in
review." Decentralized, but transition logic is scattered.

**C. Configuration-driven** -- workflow definitions are data (state graph +
transition rules in KV or config), interpreted by a lightweight engine.
Different workstream types can have different workflows without code changes.

The descriptive FSM philosophy leans toward C -- workflows as testable data,
not hardcoded logic. But this needs more discussion.

---

## Next Steps

1. Pick workflow #2 (task execution) and trace it through NATS primitives
   end to end -- every event, every KV mutation, every subject
2. Define the task state graph formally (states, transitions, triggers,
   conditions) as a mermaid diagram + transition table
3. Determine where workflow logic lives (A, B, or C above)
4. Repeat for workflow #1 (project inception)
5. Agent taxonomy emerges from workflows -- what kinds of agents do
   workflows #1-6 require?
