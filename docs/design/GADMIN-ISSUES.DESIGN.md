# GADMIN-ISSUES.DESIGN.md

> **Status:** DRAFT
> **Date:** 2026-05-17
> **Authors:** Todd Stumpf
> **Depends on:** [AGENT-NOTIFICATIONS.DESIGN.md](./AGENT-NOTIFICATIONS.DESIGN.md) (shares the local NATS bus)
> **Implementation:** partial -- skeleton on disk; see [Implementation Status](#implementation-status)

---

## Overview

`gadmin github issue` is a task-tracking surface over GitHub Issues designed
for concurrent use by multiple coding agents. Agents never mutate Issue
bodies, labels, or state directly; they post structured `/gadmin` command
comments, and a single laptop-pinned aggregator is the sole writer of
canonical fields. The append-only comment log is the durable event source;
SQLite is a derived snapshot; NATS is the local fan-out and
request-reply transport.

---

## Goals

1. **Single-writer correctness.** No two agents ever race on label/state
   writes for the same Issue. Conflicting `claim:` commands resolve
   deterministically (first comment by `created_at`, tiebreak comment id).
2. **Aggregator-down resilience.** Writes posted while the aggregator is
   offline queue safely as GH comments and apply in order on resume from a
   SQLite-stored cursor.
3. **Low-latency reads on the laptop.** `gadmin github issue list` and
   `view` return from the aggregator's SQLite snapshot via NATS
   request-reply in under 50ms wall-clock when the daemon is reachable.
4. **Low-latency `--wait-tx` on the laptop.** When NATS is reachable,
   `--wait-tx <id>` resolves within 1s of the aggregator emitting
   `gadmin.events.applied`, not the 3s GH poll interval.
5. **Ephemeral-agent friendly.** Cloud sandboxes with no NATS reachability
   still work: writes post via plain GH API; reads go direct to GH;
   `--wait-tx` polls the issue thread. Default timeout 30s, interval 3s.
6. **Low apply latency.** `gh webhook forward` is the primary ingress so
   command comments are observed within seconds, not a polling window.
   Polling is the fallback when forwarding is unavailable.
7. **Observable health.** A `gadmin.health` request-reply returns
   `{cursor_lag_seconds, last_webhook_at, db_size, nats_status}` so
   `gadmin github issue doctor` (and external dashboards) can probe the
   aggregator's state without reading SQLite directly.
8. **Backend peer parity.** Both `github-gitapi.mjs` (raw `fetch`) and
   `github-octokit.mjs` (Octokit) implement the full `cmdIssue*` surface;
   the bash dispatcher selects between them via `GADMIN_BACKEND` env var
   (`gitapi` | `octokit`, default `gitapi`), mirroring the existing
   PR-comment path. *(Status: planned — bash dispatcher currently
   hardcodes the gitapi peer. See Implementation Status / GI5.)*
9. **Scratchpad preservation.** `sync-plan` rewrites only the bytes between
   the `<!-- gadmin:autogen:start -->` and `<!-- gadmin:autogen:end -->`
   sentinels in `TODO_PLAN.md`. Everything else is byte-identical.
10. **Cross-platform.** Aggregator service ships as both a `launchd` plist
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
- **A bot account or public webhook endpoint.** The laptop `gh` token plus
  `gh webhook forward` is sufficient until proven otherwise.
- **In-band fallback writes.** Strict-aggregated is the only mode shipped;
  no client ever applies a command itself.

---

## Architecture Overview

```
                  +------------------------------------------+
                  |              GitHub Issues               |
                  |  (canonical state + append-only log)     |
                  +-----+--------------------------------+---+
                        ^                                |
       /gadmin command  |                                | webhook events
       comments         |                                v (gh webhook forward;
       (any client)     |             +---------------------------------+
                        |             |  laptop aggregator (single)     |
       +-------------+  |             |  - single writer to GH          |
       | local       |--+             |  - SQLite ~/.gadmin/issues.db   |
       | gadmin      |<------+        |  - posts /gadmin-applied        |
       +-------------+       |        |  - publishes gadmin.events.*    |
                             |        |  - serves gadmin.issues.* via   |
                             |        |    NATS request-reply           |
                             |        |  - serves gadmin.health         |
                             |        +-----------+----------+----------+
       +-------------+       |                    |          |
       | ephemeral   |       |                    | NATS     | NATS
       | cloud agent |--+    +--------------------+ req-rep  | publish
       |  (no NATS)  |  |                                    v
       +-------------+  |                            nats://127.0.0.1:4222
                        | (poll GH for apply        +-------------------+
                        |  receipt; reads direct    | other subscribers |
                        |  to GH)                   | (future dashboards|
                        +------> GH REST/GraphQL    |  agents, ...)     |
                                                    +-------------------+
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
| `tx` | Time-sortable opaque id generated client-side. Today: custom `<base36-ms>-<12-hex>` (see `newTxId` in `issue-grammar.mjs`). May be promoted to a standards UUIDv7 later; the column is opaque text either way. |
| `agent` | Free-form identity (e.g. `claude-session-NNN`, `todd-laptop`) |
| `assume-version` | Optional CAS: aggregator rejects if `issues.last_applied_tx` no longer matches |

Aggregator emits a receipt per tx:

```
/gadmin-applied tx=<uuid> status=ok
/gadmin-applied tx=<uuid> status=rejected reason=already-claimed-by:claude-A
```

Constants in code: `COMMAND_PREAMBLE = '/gadmin'`,
`APPLIED_PREAMBLE = '/gadmin-applied'`. Parsing entry points:
`parseCommand`, `parseApplied`, `formatCommand`, `formatApplied`.

### Label conventions

Only the aggregator writes these; clients only request them via commands.

| Label | Purpose |
|---|---|
| `P0` / `P1` / `P2` | Priority |
| `blocked-by:#NN` | One label per upstream blocker |
| `claimed-by:<agent>` | Active claim |
| `subsystem:<name>` | Grouping for the autogen index |

### Backend peers and dispatcher routing

Sources: `gadmin/admin/github-gitapi.mjs` (raw `fetch`),
`gadmin/admin/github-octokit.mjs` (Octokit). Both implement the same
`cmdIssue*` surface. The bash dispatcher will select via `GADMIN_BACKEND`
(planned — currently hardcodes the gitapi peer; see Implementation
Status):

```
GADMIN_BACKEND=gitapi   gadmin github issue list   # default
GADMIN_BACKEND=octokit  gadmin github issue list
```

| Function | Phase | Mechanism |
|---|---|---|
| `cmdIssueList` | A read | NATS req-rep on `gadmin.issues.list`; GH fallback |
| `cmdIssueView` | A read | NATS req-rep on `gadmin.issues.get.<n>`; GH fallback; optional `--wait-tx` |
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
| `cmdIssueNext` | B read | NATS req-rep on `gadmin.issues.list` with filters; GH fallback |
| `cmdIssueSyncPlan` | E | NATS req-rep snapshot read, rewrites autogen block in `TODO_PLAN.md` |

`emitCommand(...)` serializes a tx and posts it as a comment via
`postIssueComment`. `maybeWaitTx` resolves a tx by:

1. If NATS is reachable, request-reply on `gadmin.tx.wait` with the tx id
   and a timeout; the aggregator replies when it has observed
   `gadmin.events.applied` (or `rejected`) for that tx.
2. Otherwise, `pollAppliedReceipt` polls the issue thread for the matching
   `/gadmin-applied` reply (default `timeoutMs = 30000`,
   `intervalMs = 3000`).

### Aggregator process

Source: `gadmin/admin/issue-aggregator.mjs`.

Three concurrent responsibilities, single process, single GH-write lock:

1. **Ingress.** Primary: `gh webhook forward` subscribes to `issues` and
   `issue_comment` events and feeds them to an in-process queue. Fallback:
   periodic poll every `--interval` seconds (default 15) from the stored
   cursor. Either path yields the same `created_at`-ordered stream.
2. **Apply loop.** For each `/gadmin` command:
   - Parse via `issue-grammar.mjs`.
   - Load current state from SQLite (`issues` row).
   - Optionally enforce `assume-version` against `last_applied_tx`.
   - Apply ops to in-memory state (`applyOpsToState`).
   - Write the resolved state back to GitHub (title/body PATCH, label
     add/remove, close/reopen). This is the only path that mutates GH
     canonical fields.
   - Post a `/gadmin-applied` receipt via `postReceipt`.
   - Upsert SQLite snapshot, record tx in `tx_log`, advance cursor.
   - Publish `gadmin.events.command` on observe,
     `gadmin.events.applied` on success, `gadmin.events.rejected` on
     reject.
3. **Request-reply server.** Subscribes to `gadmin.issues.list`,
   `gadmin.issues.get.<n>`, `gadmin.tx.wait`, and `gadmin.health`
   subjects and answers from the SQLite snapshot + in-memory tx watcher.

The aggregator skips its own `/gadmin-applied` comments to avoid feedback.

### NATS bus

NATS server runs on the laptop at `nats://127.0.0.1:4222`. Both the
aggregator and clients connect with a 2s timeout; on failure they log a
warning and continue without NATS (clients fall through to direct GH /
poll paths).

**Published events:**

| Subject | Payload |
|---|---|
| `gadmin.events.command` | `{tx, issue, agent, comment_id, observed_at}` |
| `gadmin.events.applied` | `{tx, issue, diff, applied_at}` |
| `gadmin.events.rejected` | `{tx, issue, reason}` |

**Request-reply subjects:**

| Subject | Request | Reply |
|---|---|---|
| `gadmin.issues.list` | `{labels?, state?, assignee?, subsystem?}` | `[{number, title, labels, state, last_applied_tx}]` |
| `gadmin.issues.get.<n>` | (empty) | `{...issue, pending_txs: [...]}` |
| `gadmin.tx.wait` | `{tx, timeout_ms}` | `{status: 'ok'|'rejected', reason?}` once observed; or `{status: 'timeout'}` |
| `gadmin.health` | (empty) | `{cursor_lag_seconds, last_webhook_at, db_size, nats_status, version}` |

### sync-plan and TODO_PLAN.md sentinels

Source: `gadmin/admin/issue-plan-sync.mjs`.

```
<!-- gadmin:autogen:start -->
- [ ] #123 P1 [gadmin]   short title  (blocked-by: #98)
- [ ] #124 P2 [terminal] another      (claimed-by: claude-A)
<!-- gadmin:autogen:end -->
```

Constants: `SENTINEL_START`, `SENTINEL_END`. Bytes outside the sentinels
are preserved verbatim. `sync-plan` reads the snapshot via
`gadmin.issues.list` request-reply when available, falling back to a
direct GH list.

### One-time migrator

Source: `gadmin/admin/migrate-todo-plan.mjs`.

Parses the pre-existing `TODO_PLAN.md` task rows, mints one GitHub Issue
per row with derived `P*`, `subsystem:*`, and `blocked-by:#N` labels,
then collapses the migrated rows behind the autogen sentinels. Run once
per repo.

---

## State Machine

### Tx lifecycle

```
+--------+    aggregator observes    +----------+   applyOps    +---------+
| posted |-------------------------->| observed |-------------->| applied |
+--------+                           +----+-----+               +---------+
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
| posted | observed | webhook or poll | comment created_at > cursor |
| observed | applied | apply succeeded | ops valid, no version conflict |
| observed | rejected | apply refused | CAS miss or first-wins lost |
| applied | (terminal) | -- | receipt + SQLite upsert + NATS publish |
| rejected | (terminal) | -- | receipt + tx_log row + NATS publish |

---

## Data Model

SQLite at `~/.gadmin/issues.db` (path overridable via `$GADMIN_DB`).

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
+-- status           TEXT          'ok' | 'rejected' (matches receipt status=)
+-- reason           TEXT          nullable
+-- applied_at       TEXT          ISO-8601

meta
+-- key              TEXT PRIMARY KEY    'cursor', 'schema_version',
+-- value            TEXT                'last_webhook_at', ...
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
- **Webhook attestation.** Once `gh webhook forward` is the primary
  ingress, payloads must be HMAC-verified against the forwarder secret
  before entering the apply loop.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Concurrency model | Strict-aggregated CQRS | Many agents, one writer; no lock primitive needed on GH |
| Event log substrate | GH issue comments | Already durable, ordered, replayable; no extra infra |
| Aggregator host | Laptop-pinned (launchd / systemd) | Uses existing `gh` auth; no bot account or public endpoint |
| Snapshot store | SQLite at `~/.gadmin/issues.db` | Local, zero-config, transactional, easy to inspect |
| Event bus | NATS at `127.0.0.1:4222` | Pub/sub + request-reply in one transport; leaves JetStream / KV / multi-subscriber doors open |
| Read path | NATS req-rep with GH fallback | Sub-50ms reads on the laptop; ephemeral agents still work |
| Ingress | `gh webhook forward` primary, poll fallback | Low apply latency without a public endpoint |
| `--wait-tx` mechanism | NATS req-rep primary, GH poll fallback | Sub-second on the laptop; identical contract from cloud agents |
| Tx id format | Custom time-prefixed string (UUIDv7-shaped) | Time-sortable; reduces index churn in `tx_log`. Future swap to a standards UUIDv7 is a drop-in change since the wire/storage type is opaque text |
| Backend peer routing | `GADMIN_BACKEND` env var | Mirrors the PR-comment path; both peers maintained at surface parity |
| Mode | Aggregated-only | One mental model; no in-band fallback to race the aggregator |

---

## Open Questions

1. **Laptop uptime sufficiency.** How often does Todd's laptop being
   asleep cause user-visible apply lag, and does that justify a bot-hosted
   aggregator? Track via `gadmin.events.applied - command` deltas surfaced
   through `gadmin.health`.
2. **Backpressure during burst migrations.** The one-time migrator can
   mint hundreds of Issues at once; should the aggregator throttle its
   `applyOps` to stay under GH's secondary rate limit, or rely on the GH
   client's retry-after handling?
3. **`gadmin.tx.wait` semantics on rejected.** Should a rejected tx wake
   the waiter immediately with `status=rejected`, or only resolve on
   `applied`? Current design wakes on either; revisit if rejected txs
   confuse callers expecting "the change landed."

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
- **Polling-only ingress as the steady state** -- adds GH API load and
  raises apply latency above the goal; acceptable as fallback only.

---

## Future Considerations

- **JetStream durable replay log.** Promote `gadmin.events.*` to a
  persistent stream so late subscribers can replay history without
  re-walking GH comments.
- **NATS KV snapshot.** Mirror the SQLite snapshot into NATS KV so
  non-laptop subscribers (dashboards, other agents) read without a GH
  round-trip and without poking SQLite.
- **Bot account / public webhook endpoint.** Only if laptop-uptime metrics
  show unacceptable apply lag despite `gh webhook forward`.
- **Issue templates.** Structured `create` calls (subsystem-aware
  scaffolds, default labels, body skeletons).
- **Webhook HMAC attestation hardening.** Beyond verifying the forwarder
  secret: rotate keys via launchd/systemd environment file, alert on
  consecutive verification failures.

---

## Implementation Status

Status snapshot as of 2026-05-17. The full design above is the target;
this section names what's already on disk vs. what's still to build.

### Laid down

| Goal | Where | Notes |
|---|---|---|
| `/gadmin` command grammar (parse + format, command + receipt) | `gadmin/admin/issue-grammar.mjs` | Goals 1, plus smoketests `01_grammar_roundtrip.sh`, `02_grammar_rejects_malformed.sh`, `03_applied_receipt_roundtrip.sh` |
| Single-writer aggregator core | `gadmin/admin/issue-aggregator.mjs` | Apply loop, `applyOpsToState`, receipts, SQLite cursor; smoketests `04_aggregator_apply_logic.sh`, `05_aggregator_sqlite_snapshot.sh` |
| SQLite snapshot (`issues`, `tx_log`, `meta`) | `gadmin/admin/issue-aggregator.mjs:147-171` | Schema matches Data Model section |
| `gadmin.events.{command,applied,rejected}` publish | `gadmin/admin/issue-aggregator.mjs:230-235, 373, 392, 406, 425` | Publish-only side of Goal 3/4 plumbing |
| Phase A CRUD (`list`, `view`, `create`, `edit`, `comment`, `close`, `reopen`) | `gadmin/admin/github-gitapi.mjs:867-1028`, octokit peer at parity | All write paths emit `/gadmin` commands; `create` is the direct-write exception |
| Phase B workflow (`priority`, `block`, `unblock`, `claim`, `release`, `next`) | `gadmin/admin/github-gitapi.mjs:1030-1165`, octokit peer at parity | Composites over Phase A `emitCommand` |
| `--wait-tx` (GH-poll path only) | `gadmin/admin/github-gitapi.mjs:828-859` | Goal 5 (cloud-agent path); Goal 4 (laptop NATS path) still missing |
| Phase E `sync-plan` with autogen sentinels | `gadmin/admin/issue-plan-sync.mjs` | Reads via direct GH today; smoketest `06_sync_plan_preserves_scratchpad.sh` |
| Phase F one-time migrator | `gadmin/admin/migrate-todo-plan.mjs` | Smoketest `07_migrator_parses_todo_plan.sh` |
| Service units (cross-platform) | `macos/launchd/gadmin-aggregator.plist`, `local/systemd/gadmin-aggregator.service` | Goal 10 |
| Aggregator self-acknowledges deferred scope | `gadmin/admin/issue-aggregator.mjs:22-24` | "deliberately conservative: polling (not webhook forward), core ops only, no JetStream" |

### Remaining

| Goal | What's missing | Suggested entry point |
|---|---|---|
| **Goal 3** -- NATS req-rep reads | Aggregator has no `subscribe`/`respond` for `gadmin.issues.list` or `gadmin.issues.get.<n>`. Clients always read direct from GH. | Extend the NATS helper in `issue-aggregator.mjs:216-240` with subscription handlers; teach `cmdIssueList` / `cmdIssueView` / `cmdIssueNext` in both peers to try NATS first |
| **Goal 4** -- NATS-first `--wait-tx` | `maybeWaitTx` in `github-gitapi.mjs:845` only calls `pollAppliedReceipt`; the laptop case pays the 3s GH-poll interval | Add a `gadmin.tx.wait` request-reply path; fall through to existing poll on NATS unreachable |
| **Goal 6** -- `gh webhook forward` ingress | Aggregator polls only (`interval` seconds). Header comment explicitly defers webhook forwarding. | Spawn `gh webhook forward` as a child process; HMAC-verify (see Security) before queueing |
| **Goal 7** -- `gadmin.health` subject | No health endpoint exists; callers must read SQLite/logs | Add subscriber returning `{cursor_lag_seconds, last_webhook_at, db_size, nats_status, version}` |
| **Goal 8** -- Backend peer routing | Bash dispatcher hardcodes the gitapi peer at `gadmin/admin/github:825`. Octokit peer's `cmdIssue*` is dead code in `issue` mode. | Switch `cmd_issue` to read `$GADMIN_BACKEND` (default `gitapi`) and `exec` the matching `.mjs`, mirroring PR-comment dispatch |

### Test coverage status

Implemented under `test/smoketest_gadmin_issue/`:
`01_grammar_roundtrip`, `02_grammar_rejects_malformed`,
`03_applied_receipt_roundtrip`, `04_aggregator_apply_logic`,
`05_aggregator_sqlite_snapshot`, `06_sync_plan_preserves_scratchpad`,
`07_migrator_parses_todo_plan`.

Tests still to add as the remaining goals land: NATS req-rep
reads round-trip, NATS-first `--wait-tx` resolves faster than poll
fallback, webhook ingress HMAC verification, `gadmin.health` payload
shape, backend peer routing via `$GADMIN_BACKEND`.

---

## Related Documents

- [AGENT-NOTIFICATIONS.DESIGN.md](./AGENT-NOTIFICATIONS.DESIGN.md) --
  shares the `nats://127.0.0.1:4222` bus; the request-reply work in
  Remaining should reuse the same connection helper.
- [CLAI.DESIGN.md](../../CLAI.DESIGN.md) -- coding-agent launcher whose
  hooks publish the lifecycle events that an Issue-aware agent may want
  to correlate with `gadmin.events.applied`.
