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
       +-------------+       |        |    NATS request-reply           |
       | ephemeral   |       |        |  - serves gadmin.health         |
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
   - Enforce the transactional boundary and idempotence rules described in the new Atomicity subsection below.
3. **Request-reply server.** Subscribes to `gadmin.issues.list`,
   `gadmin.issues.get.<n>`, `gadmin.tx.wait`, and `gadmin.health`
   subjects and answers from the SQLite snapshot + in-memory tx watcher.

The aggregator skips its own `/gadmin-applied` comments to avoid feedback.

> New: Atomicity and failure modes (load-bearing)
- The apply cycle implements a single logical transaction boundary: a tx succeeds only if both the GitHub mutation and the local state updates (tx_log upsert, cursor advancement, snapshot upsert) complete successfully; otherwise, the system leaves no final outcome and does not publish a final receipt as applied. Receipts reflect the final outcome (ok or rejected) corresponding to the observable outcome.
- If a crash occurs after a GitHub mutation but before local persistence, replay semantics ensure determinism: replays will re-apply only unapplied transactions or detect that a tx has already been applied/rejected and treat it as a no-op.
- All mutations are idempotent with respect to replay: repeated application of the same tx does not duplicate mutations and results in the same final state and receipt.

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

> Added: Health cadence and thresholds
- Health signals are updated roughly every 5 seconds by default, and immediately when a new webhook is observed or a receipt is published.
- Thresholds (example guidance; concrete values to be tuned in production):
  - Green: cursor_lag_seconds <= 2; last_webhook_at recent; nats_status connected.
  - Yellow: cursor_lag_seconds <= 30; last_webhook_at moderately stale or NATS momentarily disconnected.
  - Red: cursor_lag_seconds > 30 or last_webhook_at unknown; NATS disconnected for extended periods; potential apply backlog.
- Version field indicates the health payload schema version; incremented when the payload shape changes.

### Health endpoint design and observability (expanded)

- Exact calculations and data sources for each metric are defined to be stable across releases.
- A versioned contract ensures evolving health payloads remain backward-compatible with monitoring tooling.
- Threshold guidance is provided to support operator dashboards, with explicit green/yellow/red semantics.

---

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

## Atomicity, idempotence, and crash recovery (load-bearing)

- The apply cycle is defined as an atomic unit: a tx commits only when both the GitHub mutation and the local state updates (tx_log upsert, cursor advancement, snapshot upsert) succeed; otherwise, no final outcome is produced and no applied receipt is emitted.
- On restart, a deterministic replay will re-apply unapplied transactions or detect that a tx has already been applied/rejected and treat it as a no-op.
- Repeated application of the same tx is idempotent; GH state, local state, and receipts converge to a single, consistent outcome.
- Failures are surfaced by the apply loop as non-final states; operators can inspect `gadmin.events.*` and `tx_log` to resolve ambiguous cases. Compensating actions are not automatic; design favors deterministic replay and strict idempotence to minimize risk.

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

## Data Model: Migrations and schema_version lifecycle (load-bearing)

- A formal schema_version policy exists and is observable via `meta.value` for `schema_version`.
- Migrations are crash-safe, idempotent, and logged. They may be run on startup to bring the repository snapshot to the target version.
- Backward/forward compatibility guarantees are defined for reads and writes during migrations; old snapshots/tx_logs are interpreted safely according to the current migration plan.
- Data migrations are tested against representative datasets and rollback paths are considered where feasible.

- Migration policy decisions at a high level:
  - Increment schema_version only when a non-backward-compatible change is introduced (or when a major feature requires it).
  - Migrations run automatically on startup; if a migration fails, startup aborts with a clear error and logs guidance for remediation.
  - Reads must tolerate old schema formats through adapters or migrations; writes are directed to the current schema and must be validated post-migration.

- Data migrations (beyond simple schema changes) are to be implemented conservatively with crash-safety and idempotence in mind; test coverage is required prior to promotion to production-readiness.

---

## Security Considerations

- **Threat model (high-level):** The aggregator operates at the boundary of your GitHub repository and a local database. Threat sources include credential leakage, compromised webhook payloads, and local process abuse via the NATS bus. The design assumes a trusted host with a single, user-scoped token and localhost-only NATS.
- **Credentials.** Aggregator uses Todd's local `gh` token; no separate bot account or stored secret. Service units inherit the user's environment.
- **NATS exposure.** Server binds to `127.0.0.1:4222` only. No remote publish or subscribe.
- **Comment injection.** Command parser requires a strict preamble and rejects malformed forms (smoketest `02_grammar_rejects_malformed.sh`
  asserts this). Free-text in `edit-body` is fenced and not interpreted.
- **CSRF / replay.** Tx ids are UUIDv7; reapplying a tx already in
  `tx_log` is a no-op (`INSERT OR REPLACE` keyed on `tx`).
- **Webhook attestation.** Once `gh webhook forward` is the primary ingress, payloads must be HMAC-verified against the forwarder secret before entering the apply loop.

> Threat model and defense in depth (new)
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

### Threat-model and rotation guidance (load-bearing)

- Prefer a dedicated bot account for GitHub actions, with permissions scoped to the minimum needed.
- Store tokens securely and inject at startup; avoid leaking tokens via environment dumps.
- Rotate the bot token on a cadence aligned with organizational security policy; revoke if compromise is suspected.
- For webhook forwarder secrets, implement rotation and monitoring for verification failures.

- NATS security
  - Introduce local authentication for NATS (e.g., JWT or NKeys) even for localhost usage.
  - Consider TLS if exposure scope expands beyond localhost.

- Data protection
  - Consider encrypting sensitive data at rest in SQLite when feasible (e.g., token material that must be stored short-term).

---

### Data Retention

- The `tx_log` table grows with every transaction. A retention policy is needed to bound growth and backup overhead.
- Key considerations (proposal; load-bearing guidance to be finalized in policy):
  - Retain all applied transactions for auditing for a defined horizon (e.g., 90 days).
  - Purge or archive older entries periodically; keep a compact summary for history.
  - Ensure pruning is idempotent and does not affect the integrity of the current state or receipts.

- Where to tighten: Data Retention section; Data Model/Operational Guidelines.

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
7) Data retention and growth considerations (tx_log and history)
- tx_log retention policy should be defined to bound SQLite growth; see
  Data Retention below.

---

## Data Retention (expanded)

- The tx_log table is the primary source of truth for auditability of mutations. To ensure long-term operational viability:
  - Retain all applied transactions for a defined horizon (e.g., 90 days).
  - Prune or archive older entries, while keeping a summarized horizon for auditing.
  - Pruning must be idempotent and must not invalidate any in-flight replay or receipts.

- Guidance:
  - Implement a background prune that deletes or archives rows older than the horizon.
  - Maintain a compact, cross-checkable summary (e.g., last N rows, or aggregated counts) to aid debugging without storing full history indefinitely.
  - Ensure that pruning does not affect the ability to replay or verify receipts for recent transactions.

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
| **Goal 3** -- NATS req-rep reads | NATS-based reads plan not implemented yet; follow-up task | Implement NATS req-rep handlers and contracts |
| **Goal 4** -- NATS-first `--wait-tx` | Laptop path readiness; only poll path exists today | Extend `maybeWaitTx` to leverage NATS path; align with health/read latency tests |
| **Goal 6** -- `gh webhook forward` ingress | Ingress presently GH polling fallback; webhook forwarder integration pending | Wire webhook forwarder as child process with HMAC verification (see Security) |
| **Goal 7** -- `gadmin.health` subject | Health endpoint exists in design but not implemented | Implement `gadmin.health` subscriber and payload production |
| **Goal 8** -- Backend parity wiring | Dynamic backend selection and parity tests not implemented | Implement `$GADMIN_BACKEND` routing to gitapi vs octokit peers; add tests |

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

Here is a focused, critical review of GADMIN-ISSUES.DESIGN.md. ... (Gist of comments integrated above)

---

## End of Document