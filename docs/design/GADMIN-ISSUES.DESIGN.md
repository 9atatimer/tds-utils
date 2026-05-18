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
   the bash dispatcher selects between them via `GADMIN_BACKEND`
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

> New: Atomicity and failure modes
> - The apply cycle is defined with a single logical transaction boundary: a tx either completes with a GitHub mutation plus local state updates (tx_log upsert, cursor advancement, receipt publication) or does not apply at all. Receipts reflect the final outcome.
> - All state mutations for a tx are idempotent with respect to replay via the tx id. If a replay occurs, the system will detect an already-applied or already-rejected tx and treat it as a no-op or a recorded outcome rather than duplicating mutations.
> - In case of crash mid-cycle, recovery relies on the tx_log cursor and the last observed state so that replay replays only unapplied transactions, preserving determinism and preventing divergence between the canonical GitHub state and the local snapshot.

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

### Health endpoint design and observability

- The health payload shape is standardized and versioned. A health read returns:
  - cursor_lag_seconds: seconds of lag between the latest webhook event and the current cursor.
  - last_webhook_at: timestamp of the last processed webhook event.
  - db_size: approximate on-disk size or row-count for the snapshot.
  - nats_status: simple health indicator (e.g., `connected` | `disconnected`), with optional latency metrics when available.
  - version: schema/shape version of the health payload.
- Health update cadence is defined to provide timely insight without introducing noise; dashboards may treat thresholded values as degraded states (green/yellow/red).

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

> Clarification: First-wins resolution for claims is enforced by the aggregator’s single-writer model. If two agents issue a `claim:` against the same issue concurrently, the one whose command is observed first (by `created_at`) wins; ties are broken by comment id. The apply loop enforces a deterministic outcome and replays are idempotent.

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

### Threat model and defense in depth (new)

- The design assumes a single, trusted aggregator process on a dedicated host;
  credentials and secrets are tightly scoped to a single user account. In
  practice, consider a dedicated bot account with least-privilege permissions
  for repository access (commenting, labeling, and state changes). Secrets
  management should avoid broad environmental leakage; load the token securely
  at process start (not broadly inherited by all child processes).
- If NATS runs on the same host, apply authentication for local clients even
  though the bus is bound to localhost; consider credentials/JWT or similar
  mechanisms to limit which processes can publish/subscribe to gadmin subjects.
- Webhook HMAC attestation must be part of the primary ingress to prevent spoofed
  webhook events. Key rotation and secret distribution should be defined (see
  Future Consider) and integrated into incident response planning.
- The scanner for assume-version should validate the exact current state version
  derived from last_applied_tx prior to applying any mutation; this prevents
  unauthorized state manipulation via replay and CAS failures.

### Token and key management guidance (brief)

- Prefer a dedicated bot account for GitHub actions, with permissions scoped to the minimum needed.
- Store tokens securely and inject at startup; avoid leaking tokens via environment dumps.
- Rotate the bot token on a cadence aligned with organizational security policy; revoke if compromise is suspected.
- For webhook forwarder secrets, implement rotation and monitoring for verification failures.

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
4. **NATS-based reads readiness (Goal 3).** Plan to implement NATS req-rep
   paths for `gadmin.issues.list` and `gadmin.issues.get.<n>`; define
   message contracts, error handling, and fallback behavior. Align with
   `--wait-tx` semantics and implement tests to validate latency goals on the laptop.
5. **Backend parity wiring (Goal 8).** Implement dynamic backend selection based on
   `$GADMIN_BACKEND` and ensure parity contracts across `gitapi` and `octokit`
   peers. Validate with automated tests.
6. **Health metrics definitions.** Provide concrete calculation formulas, update cadences,
   and clear thresholds to aid dashboards; specify a "version"ing scheme for the health
   payload so evolving health signals remain backward-compatible.

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
| Phase F one-time migrator | `gadmin/admin/migrate-todo-plan.mjs` | Smoketest `07_migrator_parses_todo_plan` |
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

```

## Reviewer Feedback

# Reviewer 1 (openai:gpt-5-nano:generalist)
**Ready:** False | **Confidence:** medium

Here is a focused, critical review of GADMIN-ISSUES.DESIGN.md. Overall, the design is thoughtful, coherent, and well-structured. It clearly articulates a single-writer CQRS pattern backed by a durable append-only log (GitHub issues), a local snapshot (SQLite), and a local NATS bus. The division of responsibilities, state-machine framing, and the consideration of cloud-ephemeral agents are strong points. There are, however, several important gaps and ambiguities that could impact correctness, reliability, and security. Below I list the most significant issues, with actionable feedback and cross-references to sections.

Key issues and gaps (WHAT is missing or unclear)

1) Atomicity and failure modes between GitHub mutations and local state ( Aggregator process)
- What’s missing: The design describes applying operations to GitHub (mutating canonical fields) and then updating SQLite (snapshot upsert, tx_log, cursor) and emitting receipts. It does not clearly define transactional guarantees across these steps. If a GitHub update succeeds but the local snapshot/tx_log-update fails (or the process crashes mid-step), the system could drift between the GitHub canonical state and the local store, or produce conflicting receipts.
- Why this matters: The single-writer invariant is predicated on consistent, deterministic mutation ordering. Without a defined atomic boundary or a robust compensation path, crashes or partial failures could undermine correctness and make replay/rehydration brittle.
- Suggested clarifications/additions (WHAT to require, not HOW to implement): 
  - Explicitly state the transactional boundary for each apply cycle. For example: either both the GH mutation and the corresponding local state updates (tx_log insert, cursor advance, snapshot upsert) succeed or neither do; receipts should reflect the final outcome.
  - Define idempotence rules for GH mutations and local writes in the face of retries (e.g., if an operation is re-applied due to a replay, it must be a no-op or be safely re-entrant).
  - Specify how failures are surfaced to the caller and how compensating actions (if any) are taken to restore consistency.
  - Include a high-level recovery plan if the process crashes after a GH mutation but before local persistence (and vice versa): how will replay handle potentially partially-applied txs?
- Where to tighten: Design/Aggregator processing flow (section “Aggregator process” and “Tx lifecycle”).

2) Data model migrations and schema_version lifecycle
- What’s missing: The Data Model defines meta with a schema_version, but there is no migration strategy or upgrade path described. How will the system detect, migrate, and validate schema changes across releases? How will old snapshots or tx_logs be migrated safely?
- Why this matters: Without a defined migration plan, upgrades could corrupt the database or break compatibility with new code paths (especially when the autogen plan or tx_log schema changes). This is critical for long-lived deployments and for edge cases (e.g., migrating from 1.x to 2.x).
- Suggested clarifications/additions:
  - Add a clear schema-versioning policy and migration procedure, including:
    - When and how schema_version is bumped.
    - How migrations are performed (idempotent, crash-safe, logged).
    - Backward-compatibility guarantees for reads and writes during a migration.
  - Specify how snapshots (issues, tx_log, meta) are migrated and how existing data is validated post-migration.
- Where to tighten: Data Model section; Implementation Status may need updates to reflect migrations.

3) Health endpoint design and observability expectations
- What’s missing: The health payload is specified as {cursor_lag_seconds, last_webhook_at, db_size, nats_status}. However, there are no concrete definitions for how to compute these values, update cadence, or what constitutes “healthy” versus degraded. The “version” field is shown in the health reply for gadmin.health, but its source is not described.
- Why this matters: Operators rely on health signals to decide if the aggregator is live, lagging, or degraded. Ambiguities around calculation, staleness, and expected ranges can lead to misinterpretation and poor operational decisions.
- Suggested clarifications/additions:
  - Define exact calculation formulas and update cadence for:
    - cursor_lag_seconds (how it's computed relative to observed webhook stream vs. current cursor).
    - last_webhook_at (timestamp of the last processed webhook event).
    - db_size (bytes or row count, and how/when it’s updated).
    - nats_status (connected/disconnected, and how it’s inferred when NATS is optional).
  - Define a stable, versioned health payload schema and a schema-version counter if the health shape evolves.
  - Provide thresholds or qualitative states (green/yellow/red) to assist dashboards, and note any dependencies (e.g., NATS availability vs. webhook availability) that could trigger degraded modes.
- Where to tighten: Security Considerations and Observability sections; Open Questions may partially address health needs but the data shape needs concrete definitions.

4) NATS-based reads (Goal 3) are not implemented yet
- What’s missing: The design explicitly labels Goal 3 (NATS req-rep reads) as not implemented yet and lists it as “Remaining.” The current read path relies on direct GH reads or polling. This undermines the stated latency goals on the laptop and leaves a gap between design intent and implementation.
- Why this matters: Sub-50ms reads on the laptop depend on the NATS req-rep path and a local snapshot. Without a concrete plan and test coverage for the read path, a major performance/consistency assumption remains unvalidated.
- Suggested clarifications/additions:
  - Provide a concrete plan and entry points for implementing NATS req-rep handlers for gadmin.issues.list and gadmin.issues.get.<n>, including expected message formats, error handling, and fallbacks.
  - Define how the read path will interact with the local SQLite snapshot, including how staleness will be bounded when NATS is available vs. when it is not.
  - Align read-path semantics with --wait-tx behavior to ensure consistent researcher/observer experience across NATS and GH fallback modes.
- Where to tighten: Implementation Status and Architecture Overview; consider adding lightweight diagrams or a minimal API contract for the read path.

5) Backend peer parity and routing (Goal 8) implementation status
- What’s missing: Backend parity between gitapi and octokit is planned but not yet implemented. The bash dispatcher currently hardcodes the gitapi peer. This creates drift between the design intentions and actual behavior, and undermines the stated goal of surface parity.
- Why this matters: If a user switches backend via GADMIN_BACKEND, or if future changes rely on octokit parity, the current state could cause confusing behavior or errors. It also increases maintenance burden if the code path diverges.
- Suggested clarifications/additions:
  - Flesh out a concrete implementation plan for dynamic backend selection, including how the dispatcher detects GADMIN_BACKEND and how it dispatches to the correct peer module.
  - Include a simple compatibility contract (the same function signatures and return shapes) that both peers must satisfy, with clear error handling for mismatches.
- Where to tighten: Open Questions/Implementation Status.

6) Security posture: token handling, forwarder attestation, and deployment risk
- What’s missing: The document asserts credentials are local to the user for the laptop and that NATS is bound to localhost, as well as HMAC attestation for webhook payloads. However:
  - There is no explicit threat model or guidance on token scope, rotation, or revocation for the GitHub token.
  - HMAC attestation details (which header, which algorithm, secret rotation process) are not specified.
  - There’s no explicit discussion of how the system handles token leakage, process isolation, or secrets management within systemd/launchd units.
- Why this matters: The design hinges on a trustworthy, single-writer model that depends on local credentials and webhook attestation. Without concrete security boundaries and rotation strategies, there are real risk vectors.
- Suggested clarifications/additions:
  - Add a concise threat model and explicit security assumptions (scope-limited credentials, least privilege, rotation, revocation, and how secrets are stored in the host environment).
  - Provide concrete guidance for rotating the gh token and for rotating/validating the forwarder webhook secret, including key rotation cadence and alerting on repeated verification failures.
  - Document incident response expectations if the forwarder secret or token is compromised.
- Where to tighten: Security Considerations; Open Questions.

7) Data retention and growth considerations (tx_log and history)
- What’s missing: The tx_log table stores every tx with a corresponding applied/rejected status. There is no stated policy on how long tx_log rows are retained, nor any plan for pruning or archiving, which could affect SQLite size and performance over time.
- Why this matters: Long-running usage could lead to unbounded growth in tx_log, impacting performance and backup/restore overhead.
- Suggested clarifications/additions:
  - Define retention policy for tx_log (e.g., archive or purge after X days, or after a successful applied receipt and a fixed horizon).
  - Consider a compacted or summarized view strategy for historical data that is no longer needed for tail-consistency checks.
- Where to tighten: Data Model or Operational Guidelines.

8) Open questions alignment with design and risk forecast
- The document already lists several open questions (laptop uptime, backpressure during migrations, and wait semantics). These are important risk areas; consider resolving or at least scoping acceptable risk tolerances and migration/backpressure strategies in the design, or clearly marking as “assumptions” with planned mitigations.

Strengths worth calling out (what’s sound and well-done)

- Clear architecture and data-flow narrative: The combination of GitHub issues as the canonical log, SQLite as a derived snapshot, and NATS for local pub/sub is well articulated. The separation of concerns (ingress, apply loop, request-reply server) is clean.
- Deterministic, first-wins concurrency model: The explicit rule for claim/first-wins and the use of created_at ordering with a tiebreak by comment id is a solid way to ensure deterministic outcomes in a multi-agent scenario.
- Comprehensive state-machine framing: The Tx lifecycle diagram and the mapping of commands to receipts and event publications demonstrate thoughtful end-to-end traceability.
- Observability/value of health signals: The inclusion of a gadmin.health response with multiple signals shows a careful eye toward operability and dashboards.
- Forward compatibility with multiple backends: The intention to support both gitapi and octokit peers, and to switch via GADMIN_BACKEND, is a strong design choice for portability and resilience (even though it’s not fully implemented yet).
- Ephemeral-agent considerations: The design acknowledges cloud sandbox scenarios and provides fallback paths (GH direct reads / polls) to preserve usability.

Recommendation on readiness

- The document is strong in concept and structure but has several blocking gaps that should be closed before approval:
  - Define transactional guarantees and error-handling boundaries between GH mutations and local state updates (Atomicity section).
  - Add a formal data migration strategy and schema_version lifecycle (Data Model).
  - Provide concrete planning and contracts for the NATS-based reads path (Goal 3) and ensure it’s on track as a prioritized follow-up.
  - Strengthen the security model with concrete token rotation, HMAC attestation details, and threat model coverage.
  - Clarify health metrics definitions and thresholds, so operators have concrete interpretation guidance.
  - Add data-retention guidance for tx_log and snapshot growth considerations.
  - Ensure backend parity wiring is implemented and tested (dynamic backend selection) so implementation matches the documented goals.
- Given these gaps, I would not approve as-is. A revised design addressing the atomicity guarantees, migration plan, health/security specifics, and the NATS-read path would substantially improve confidence in correctness and operational readiness.

Bottom-line verdict: The design is solid in intent and structure but requires concrete specifications in key correctness and security areas (not just openness to future work) to be considered ready for approval.

---

## Implementation Details (Cross-References and Load-Bearing Notes)

- Atomicity and failure modes (Design): The apply cycle boundary and idempotence rules are load-bearing for correctness and should be explicitly codified in the Aggregator processing flow.
- Data migrations (Data Model): Schema_version lifecycle is load-bearing for upgrades and long-term correctness; migrations must be crash-safe and logged.
- Health signals (Health endpoint): Precise definitions for calculation and thresholds are load-bearing for operability.
- NATS reads (Architecture): A concrete plan for NATS-based reads is necessary for performance and correctness guarantees on latency-sensitive paths.
- Backend parity (Open Questions): Dynamic backend selection is a design requirement; the current status should be updated to reflect concrete wiring and tests.
- Security posture (Security Considerations): Threat model, token rotation, webhook attestation, and NATS auth are load-bearing for risk management; fill in explicit guidance and procedures.
- Data retention (Data Model): tx_log retention policy is a practical consideration for operational stability.

---

## End of Document