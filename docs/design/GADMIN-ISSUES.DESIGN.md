# GADMIN-ISSUES.DESIGN.md

> **Status:** IMPLEMENTED
> **Date:** 2026-05-17
> **Authors:** Todd Stumpf
> **Depends on:** [AGENT-NOTIFICATIONS.DESIGN.md](./AGENT-NOTIFICATIONS.DESIGN.md) (shares the local NATS bus)

---

## Overview

`gadmin github issue` is a task-tracking surface over GitHub Issues designed
for concurrent use by multiple coding agents. Agents never mutate Issue
bodies, labels, or state directly; they post structured `/gadmin` command
comments, and a single laptop-pinned aggregator is the sole writer of
canonical fields. The append-only comment log is the durable event source;
SQLite is a derived snapshot; NATS is a fan-out event bus.

---

## Goals

1. **Single-writer correctness.** No two agents ever race on label/state
   writes for the same Issue. Conflicting `claim:` commands resolve
   deterministically (first comment by `created_at`, tiebreak comment id).
2. **Aggregator-down resilience.** Writes posted while the aggregator is
   offline queue safely as GH comments and apply in order on resume from a
   SQLite-stored cursor.
3. **Ephemeral-agent friendly.** Cloud sandboxes with no NATS reachability
   still work: writes post via plain GH API; `--wait-tx` polls the issue
   thread for the apply receipt. Default timeout 30s, poll interval 3s.
4. **Scratchpad preservation.** `sync-plan` rewrites only the bytes between
   the `<!-- gadmin:autogen:start -->` and `<!-- gadmin:autogen:end -->`
   sentinels in `TODO_PLAN.md`. Everything else is byte-identical.
5. **Cross-platform.** Aggregator service ships as both a `launchd` plist
   (macOS) and a `systemd` unit (Linux). Per-CLAUDE.md, bash dispatcher
   tolerates BSD and GNU tool variants.

---

## Non-Goals

- **GitHub Projects / native sub-issues / milestones.** Out of scope; label
  conventions (`P0..P2`, `blocked-by:#NN`, `subsystem:*`) carry the same
  information without lock-in.
- **Claim TTLs / heartbeats.** Claims are explicit-release only. Stale
  claims are a human-scale problem, not a system one.
- **Multi-writer aggregators.** Exactly one aggregator per repo; replacing
  hardware means pointing a new install at the same `gh` identity.
- **A bot account or public webhook endpoint.** The laptop `gh` token is
  sufficient until proven otherwise.
- **In-band fallback writes.** Strict-aggregated is the only mode shipped;
  no client ever applies a command itself.

---

## Architecture Overview

```
                      +------------------------------------------+
                      |              GitHub Issues               |
                      |  (canonical state + append-only log)     |
                      +-----+-------------------------------+----+
                            ^                               |
        /gadmin command     |                               | poll for new
        comments            |                               v comments
        (any client)        |               +---------------------------------+
                            |               |  laptop aggregator (single)     |
        +----------------+  |               |  - single writer to GH          |
        | local gadmin   |  |               |  - SQLite ~/.gadmin/issues.db   |
        | client         |--+               |  - posts /gadmin-applied        |
        +----------------+                  |  - publishes gadmin.events.*    |
                                            +---------------+-----------------+
        +----------------+                                  |
        | ephemeral      |                                  | NATS publish
        | cloud agent    |--+ (poll GH for                  v
        |  (no NATS)     |  | apply receipt)        nats://127.0.0.1:4222
        +----------------+  |                       (subscribers: future
                            |                        fan-out, dashboards)
                            |
                            +-> GH REST/GraphQL
```

---

## Design

### /gadmin command-comment grammar

Source: `gadmin/admin/issue-grammar.mjs`.

A command comment starts with a `/gadmin` preamble line. Comments without
the preamble are human discussion and ignored by the aggregator.

```
/gadmin tx=<uuid> agent=<id> [assume-version=<prev-tx>]
priority: P1
add-label: blocked-by:#42
remove-label: blocked-by:#42
claim:
release:
close: completed
reopen:
edit-title: New title
edit-body: |
  ...new body, fenced...
```

| Field | Purpose |
|---|---|
| `tx` | UUID generated client-side; primary key of the tx log |
| `agent` | Free-form identity (e.g. `claude-session-NNN`, `todd-laptop`) |
| `assume-version` | Optional CAS: aggregator rejects if `issues.last_applied_tx` no longer matches |

Aggregator emits a receipt per tx:

```
/gadmin-applied tx=<uuid> status=ok
/gadmin-applied tx=<uuid> status=rejected reason=already-claimed-by:claude-A
```

Constants in code: `APPLIED_PREAMBLE = '/gadmin-applied'`. Parsing entry
points: `parseCommand`, `parseApplied`, `formatCommand`, `formatApplied`.

### Backend peers

Source: `gadmin/admin/github-gitapi.mjs` (raw `fetch`),
`gadmin/admin/github-octokit.mjs` (Octokit client). Both implement the same
`cmdIssue*` surface; the bash dispatcher currently routes `issue` to the
gitapi peer. The octokit peer exists for parity and future selection.

| Function | Phase | Mechanism |
|---|---|---|
| `cmdIssueList` | A read | direct GH REST list |
| `cmdIssueView` | A read | direct GH REST get (+ optional `--wait-tx`) |
| `cmdIssueCreate` | A write (special) | direct GH POST -- no Issue exists yet to comment on |
| `cmdIssueEdit` | A write | emits `edit-title` / `edit-body` command |
| `cmdIssueComment` | A write (plain) | posts a non-command comment verbatim |
| `cmdIssueClose` | A write | emits `close:` command |
| `cmdIssueReopen` | A write | emits `reopen:` command |
| `cmdIssuePriority` | B workflow | emits `remove-label: P*` + `add-label: P<n>` |
| `cmdIssueBlock` | B workflow | emits `add-label: blocked-by:#<m>` |
| `cmdIssueUnblock` | B workflow | emits `remove-label: blocked-by:#<m>` (one or all) |
| `cmdIssueClaim` | B workflow | emits `claim:` (aggregator enforces first-wins) |
| `cmdIssueRelease` | B workflow | emits `release:` |
| `cmdIssueNext` | B read | direct GH list, in-process filter on labels |
| `cmdIssueSyncPlan` | E | rewrites the autogen block in `TODO_PLAN.md` |

`emitCommand(octokit, owner, repo, issueNumber, ops, { assumeVersion })`
serializes a tx and posts it as a comment via `postIssueComment`.
`maybeWaitTx` -> `pollAppliedReceipt` blocks on the issue thread for the
matching `/gadmin-applied` reply (default `timeoutMs = 30000`,
`intervalMs = 3000`).

### Aggregator process

Source: `gadmin/admin/issue-aggregator.mjs` (`main()` at line 460).

Loop:

1. Fetch comments since the stored cursor (`meta.cursor`).
2. For each `/gadmin` command comment in `created_at` order:
   - Parse via `issue-grammar.mjs`.
   - Load current state from SQLite (`issues` row).
   - Optionally enforce `assume-version` against `last_applied_tx`.
   - Apply ops to in-memory state (`applyOpsToState`).
   - Write the resolved state back to GitHub (title/body PATCH, label
     add/remove, close/reopen). This is the only path that mutates GH
     canonical fields.
   - Post a `/gadmin-applied` receipt via `postReceipt`.
   - Upsert SQLite snapshot, record tx in `tx_log`, advance cursor.
   - Publish to NATS (if connected): `gadmin.events.command` on observe,
     `gadmin.events.applied` on success, `gadmin.events.rejected` on
     reject.
3. Skip the aggregator's own `/gadmin-applied` comments to avoid feedback.

Webhook ingress was scoped as `gh webhook forward`; current implementation
uses periodic polling with the cursor. Either approach yields the same
event ordering since `created_at` is the source of truth.

### NATS bus

NATS server runs on the laptop at `nats://127.0.0.1:4222`. The aggregator
connects with a 2s timeout; on failure it logs a warning and continues
without publishing. Clients today do not subscribe.

Subjects published by the aggregator:

| Subject | Payload |
|---|---|
| `gadmin.events.command` | `{tx, issue, agent, comment_id, observed_at}` |
| `gadmin.events.applied` | `{tx, issue, diff, applied_at}` |
| `gadmin.events.rejected` | `{tx, issue, reason}` |

Subjects intentionally **not** implemented in v0 (see Future Considerations):
`gadmin.issues.list`, `gadmin.issues.get.<n>`, `gadmin.tx.wait`,
`gadmin.health`.

### sync-plan and TODO_PLAN.md sentinels

Source: `gadmin/admin/issue-plan-sync.mjs`.

```
<!-- gadmin:autogen:start -->
- [ ] #123 P1 [gadmin]   short title  (blocked-by: #98)
- [ ] #124 P2 [terminal] another      (claimed-by: claude-A)
<!-- gadmin:autogen:end -->
```

Constants: `SENTINEL_START`, `SENTINEL_END`. Bytes outside the sentinels are
preserved verbatim -- the human scratchpad section of `TODO_PLAN.md` is
untouched.

### One-time migrator

Source: `gadmin/admin/migrate-todo-plan.mjs` (238 lines).

Parses the pre-existing `TODO_PLAN.md` task rows, mints one GitHub Issue
per row with derived `P*`, `subsystem:*`, and `blocked-by:#N` labels, then
collapses the migrated rows behind the autogen sentinels. Run once per
repo; idempotency is bounded by a per-row id parser.

---

## State Machine

### Tx lifecycle

```
+--------+    aggregator observes     +----------+   applyOps    +---------+
| posted |--------------------------->| observed |-------------->| applied |
+--------+                            +----+-----+               +---------+
                                           |
                                           | assume-version fails
                                           | or claim already taken
                                           v
                                       +----------+
                                       | rejected |
                                       +----------+
```

| From | To | Trigger | Condition |
|------|-----|---------|-----------|
| posted | observed | aggregator poll/webhook | comment created_at > cursor |
| observed | applied | apply succeeded | ops valid, no version conflict |
| observed | rejected | apply refused | CAS miss or first-wins lost |
| applied | (terminal) | -- | receipt + SQLite upsert + NATS publish |
| rejected | (terminal) | -- | receipt + tx_log row + NATS publish |

---

## Data Model

SQLite at `~/.gadmin/issues.db` (path overridable via aggregator flag).

```
issues
+-- number           INTEGER PRIMARY KEY
+-- state            TEXT          ('open' | 'closed')
+-- title            TEXT
+-- body             TEXT
+-- labels           TEXT          JSON array of label names
+-- assignees        TEXT          JSON array of logins
+-- last_applied_tx  TEXT          most recent tx that mutated this issue
+-- updated_at       TEXT          ISO-8601

tx_log
+-- tx               TEXT PRIMARY KEY
+-- issue            INTEGER       FK loose ref to issues.number
+-- agent            TEXT
+-- comment_id       INTEGER       source GH comment id
+-- status           TEXT          'applied' | 'rejected'
+-- reason           TEXT          nullable
+-- applied_at       TEXT          ISO-8601

meta
+-- key              TEXT PRIMARY KEY    'cursor', 'schema_version', ...
+-- value            TEXT
```

---

## Security Considerations

- **Credentials.** Aggregator uses Todd's local `gh` token; no separate
  bot account or stored secret. Service units inherit the user's
  environment.
- **NATS exposure.** Server binds to `127.0.0.1:4222` only. No remote
  publish or subscribe.
- **Comment injection.** Command parser requires a strict preamble and
  rejects malformed forms (smoketest `02_grammar_rejects_malformed.sh`
  asserts this). Free-text in `edit-body` is fenced and not interpreted.
- **CSRF / replay.** Tx ids are UUIDv7; reapplying a tx already in
  `tx_log` is a no-op (`INSERT OR REPLACE` keyed on `tx`).
- **Webhook attestation.** Not relevant in v0 -- ingress is poll-only.
  If `gh webhook forward` is adopted later, payloads must be HMAC-verified.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Concurrency model | Strict-aggregated CQRS | Many agents, one writer; no lock primitive needed on GH |
| Event log substrate | GH issue comments | Already durable, ordered, replayable; no extra infra |
| Aggregator host | Laptop-pinned (launchd / systemd) | Uses existing `gh` auth; no bot account or public endpoint |
| Snapshot store | SQLite at `~/.gadmin/issues.db` | Local, zero-config, transactional, easy to inspect |
| Event bus | NATS at `127.0.0.1:4222` | Leaves JetStream / KV / multi-subscriber doors open |
| Read path | Direct GH | Avoids a hard dependency on NATS for routine `list`/`view` |
| `--wait-tx` mechanism | Poll GH comments | Works identically from laptop or ephemeral cloud agent |
| Tx id format | UUIDv7 | Time-sortable; reduces index churn in `tx_log` |
| Mode | Aggregated-only | One mental model; no in-band fallback to race the aggregator |

---

## Open Questions

1. **Laptop uptime sufficiency.** How often does Todd's laptop being
   asleep cause user-visible apply lag, and does that justify a bot-hosted
   aggregator? Track via `gadmin.events.applied - command` deltas.
2. **Webhook adoption.** Polling is simple but adds steady-state GH API
   load. `gh webhook forward` is the planned upgrade; not yet wired.
3. **Octokit peer routing.** The bash dispatcher hardcodes the gitapi
   peer for `issue`. Selection by env var (mirroring the PR-comment path)
   is implemented in code but not exposed.

---

## Rejections

- **In-band fallback writes** -- would race the aggregator and break the
  single-writer guarantee; the entire concurrency story relies on it.
- **GitHub Projects as the snapshot** -- API is rate-limited, schema is
  rigid, no offline cache, harder to migrate off later.
- **Native GH sub-issues** -- newer API surface, less tooling, label-based
  `blocked-by:#N` gives equivalent expressiveness today.
- **Claim TTLs / heartbeats** -- stale-claim cleanup is rare and human-
  recoverable; not worth the protocol surface area.
- **Multi-writer aggregators** -- contradicts the single-writer invariant;
  would require a separate consensus layer.
- **Unix socket transport** -- works for local clients but blocks future
  fan-out (additional subscribers, dashboards) that NATS gives for free.

---

## Future Considerations

- **NATS request-reply** (`gadmin.issues.list`, `gadmin.issues.get.<n>`,
  `gadmin.tx.wait`, `gadmin.health`) -- makes `--wait-tx` instant on the
  laptop and offloads `list`/`view` from GH. Wire format already drafted in
  this doc; the aggregator only needs to add subscribe handlers.
- **JetStream durable replay log** -- promote `gadmin.events.*` to a
  persistent stream so late subscribers can replay history.
- **NATS KV snapshot** -- mirror the SQLite snapshot into KV so non-laptop
  subscribers (future dashboards) read without a GH round-trip.
- **`gh webhook forward` ingress** -- replace polling; reduce GH API
  pressure and apply latency.
- **Bot account / public webhook** -- only if laptop-uptime metrics show
  unacceptable apply lag.
- **Issue templates** -- structured `create` calls (subsystem-aware
  scaffolds).

---

## Related Documents

- [AGENT-NOTIFICATIONS.DESIGN.md](./AGENT-NOTIFICATIONS.DESIGN.md) --
  shares the `nats://127.0.0.1:4222` bus; future request-reply work here
  should reuse the same connection helper.
- [CLAI.DESIGN.md](../../CLAI.DESIGN.md) -- coding-agent launcher whose
  hooks publish the lifecycle events that an Issue-aware agent may want
  to correlate with `gadmin.events.applied`.
