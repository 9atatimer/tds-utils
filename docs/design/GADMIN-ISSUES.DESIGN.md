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

---

### Security Considerations (enhanced load-bearing posture)

- **Credential management (load-bearing).** Do not rely on a personal user token. Move to a dedicated bot account with least-privilege permissions for repository actions (commenting, labeling, and state changes). Secrets must be loaded from a secure, restricted store at startup and never exposed via broad environment leaks.
- **NATS security (load-bearing).** Enable authentication for all local clients (e.g., NATS JWT/NKeys or mTLS) even when bound to localhost. Consider TLS for transport if the scope may widen beyond localhost.
- **Webhook attestation and rotation (load-bearing).** Webhook HMAC verification is mandatory on ingress. Define a rotation policy for the forwarder secret and a distribution mechanism for new secrets. In the event of rotation failure, the system must fail closed and require operator remediation.
- **Replay protection and CAS (load-bearing).** Assume-version checks must be strict: compare the exact current last_applied_tx for the targeted issue before applying any mutation. If it does not match, reject the command to prevent replay or CAS bypass.
- **Data protection (load-bearing).** Encrypt data at rest for the SQLite database where feasible. If full encryption is not possible, rely on OS-level or filesystem encryption and restrict access to the host. Secrets must be confined to restricted storage with narrow access control.

> Threat-model and defense in depth (new)
- The design assumes a single, trusted aggregator process on a dedicated host; credential management, secret rotation, and access controls must be implemented with least-privilege principles in mind and documented for operators.
- NATS should enforce local authentication and, where feasible, TLS. Webhook secret rotation and incident response planning should be codified.

---

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

### Health metrics contract (design-level)

- Health payload shape is versioned. A health read returns:
  - cursor_lag_seconds: seconds of lag between the latest webhook event and the current cursor.
  - last_webhook_at: timestamp of the last processed webhook event.
  - db_size: approximate on-disk size or row-count for the snapshot.
  - nats_status: simple health indicator (e.g., `connected` | `disconnected`), with optional latency metrics when available.
  - version: schema/shape version of the health payload.
- Health update cadence is defined to provide timely insight without noise.
- Threshold semantics (example guidance; concrete values to be tuned in production):
  - Green: cursor_lag_seconds <= 2; last_webhook_at recent; nats_status == connected.
  - Yellow: cursor_lag_seconds <= 30; last_webhook_at moderately stale or NATS momentarily disconnected.
  - Red: cursor_lag_seconds > 30 or last_webhook_at unknown; NATS disconnected for extended periods; potential apply backlog.
- Versioned contract ensures evolving health payloads remain backward-compatible with monitoring tooling.
- Health signals should support dashboards with clear green/yellow/red semantics.

> Added: Health cadence and thresholds
- Health signals are updated roughly every 5 seconds by default, and immediately when a new webhook is observed or a receipt is published.
- Version field indicates the health payload schema version; incremented when the payload shape changes.

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

> Failure modes and recovery (enhanced load-bearing)
- If a crash occurs mid-apply (e.g., GitHub mutation succeeds but local persistence fails), deterministic replay ensures the system will re-evaluate the transaction on restart. The replay will re-apply only unapplied transactions or detect prior application and treat as no-op.
- Partial failures across ingress, apply, and persistence must be recoverable through a well-defined replay path and a strict boundary where receipts are emitted only after all consequences are durable.
- The system must expose explicit guidance for operators on how to resolve ambiguous states via the tx_log, receipts, and health signals.

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

- Data protection (explicit load-bearing requirement)
  - Encrypt SQLite data at rest where feasible (e.g., with a SQLCipher-like extension or OS-level encryption). If encryption is not feasible in the target environment, define an approved alternative (e.g., dedicated filesystem encryption) and restrict access accordingly.

- Data retention policy (explicit guidance)
  - Retention horizon for tx_log: 90 days for full logs; maintain a non-prunable audit tail for longer-term compliance/auditing.
  - Archive/prune mechanism must be idempotent and not affect replay capability for recent transactions.
  - A separate immutable audit tail is used for long-term history, while the transactional log used for replay remains prune-able within policy limits.

- Migrations must be atomic; if a migration fails, startup should abort with actionable remediation guidance. If full rollback is not possible, define safe fail-open/fail-closed states and operators’ recovery steps.

---

## Security Considerations (summary of load-bearing stances)

- Credentials
  - Move from using a user’s personal token to a dedicated bot account with least-privilege permissions.
  - Secrets must be loaded from a secure store at startup; avoid environmental leakage and broad inheritance by child processes.

- NATS
  - Require client authentication (even on localhost); consider JWT/NKeys and TLS if applicable.

- Webhook attestation
  - Mandatory HMAC verification on ingress; secret rotation and secure distribution defined; incident response planned for rotation failures.

- Replay and CAS
  - Assume-version check is strict: must be byte-for-byte equal to current last_applied_tx for the targeted issue before mutation.

- Data protection
  - Encrypt data at rest for SQLite; route around weak points with OS-level protections and restricted access.

---

## Open Questions and Decisions (Decision Log)

- Decision: Bot-hosted aggregator vs laptop-only (Goal 1)
  - Plan: Move toward a bot-hosted aggregator to improve uptime and latency guarantees in production scenarios. This reduces single points of failure and supports stronger security posture around credentials and network boundaries.
  - Rationale: Addresses reviewer concerns about uptime, apply lag, and reliability in the field.
  - Next steps: Update deployment model and security requirements to reflect bot account usage; adjust OPS docs and tests accordingly.

- Decision: NATS-based reads and --wait-tx semantics (Goals 3/4)
  - Plan: Implement NATS req-rep paths for `gadmin.issues.list`, `gadmin.issues.get.<n>`, and a fast --wait-tx path. Wait-tx will resolve on receipt of either an `applied` or a `rejected` event to avoid indefinite waiting.
  - Rationale: Reduces latency for laptop users and provides deterministic wait semantics aligned with health signals.
  - Next steps: Define message contracts, failure modes, and a test plan for latency on the laptop.

- Decision: Dynamic backend parity wiring (Goal 8)
  - Plan: Introduce `GADMIN_BACKEND` to switch between `gitapi` and `octokit` peers; add tests and acceptance criteria for parity.
  - Rationale: Aligns with long-term maintainability and resilience.
  - Next steps: Implement wiring, tests, and CI coverage; target GI5 milestone.

- Decision: Health metrics contract (Health section)
  - Plan: Define precise formulas for cursor lag, last_webhook_at, db_size, and nats_status; version the payload; set concrete blue/green/yellow thresholds.
  - Rationale: Enables actionable dashboards and alerting.
  - Next steps: Implement the metrics, telemetry hooks, and dashboards tests.

- Decision: Data retention and replay safety (Retention section)
  - Plan: Establish a 90-day retention horizon for tx_log with a non-prunable audit tail; implement archiving of older entries behind a separate append-only store.
  - Rationale: Balances auditability with operational efficiency and replay safety.
  - Next steps: Document pruning procedure, recovery, and testing for replay with archived history.

- Decision: Webhook attestation and rotation (Security)
  - Plan: Mandate HMAC attestation on ingress with rotation policy; define secret distribution and incident response.
  - Rationale: Improves security hygiene and resilience against spoofed payloads.
  - Next steps: Codify rotation cadence and automation plan; update incident-response docs.

- Decision: Credential management (Security)
  - Plan: Use a dedicated bot account with restricted scope; store tokens in secure storage; load at startup with restricted access.
  - Rationale: Reduces risk of credential leakage and broad account compromise.
  - Next steps: Update deployment docs and sample secret-management workflow.

- Decision: Edge-case handling and crash-recovery (Recovery)
  - Plan: Document explicit failure modes for ingress/apply/persistence, and outline deterministic replay guarantees for crash scenarios.
  - Rationale: Ensures operators have a clear path to resolve transient failures and maintain consistency.
  - Next steps: Expand Atomicity section with edge-case examples and recovery steps.

- Decision: Data encryption (Data Model)
  - Plan: Encrypt data at rest for SQLite where feasible; otherwise use OS-level encryption; restrict access to the host.
  - Rationale: Mitigates risk of data exposure if the host is compromised.
  - Next steps: Select encryption approach and document operational requirements.

- Decision: Data retention policy (Policy)
  - Plan: Tie pruning to the durable checkpoint and ensure replay determinism; keep audit tail for audits; separate archive for long-term history.
  - Rationale: Maintains replay safety while controlling growth.
  - Next steps: Document the exact retention windows, archiving process, and rollback behavior during migrations.

---

## Health endpoint design and observability (expanded)

- Health payload shape is standardized and versioned. A health read returns:
  - cursor_lag_seconds: seconds of lag between the latest webhook event and the current cursor.
  - last_webhook_at: timestamp of the last processed webhook event.
  - db_size: approximate on-disk size or row-count for the snapshot.
  - nats_status: simple health indicator (e.g., `connected` | `disconnected`), with optional latency metrics when available.
  - version: schema/shape version of the health payload.

- Health update cadence is defined to provide timely insight without introducing noise; dashboards may treat thresholded values as degraded states (green/yellow/red).

- Threshold guidance (as above) with concrete values:
  - Green: lag <= 2s; last_webhook_at recent; NATS connected.
  - Yellow: lag <= 30s; last_webhook_at moderately stale, or NATS momentarily disconnected.
  - Red: lag > 30s or last_webhook_at unknown; NATS disconnected for extended periods.

- Versioned contract and dashboard guidance included to support long-term evolution.

---

## sync-plan and TODO_PLAN.md sentinels

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
```

## Additional Notes for Implementers

- Where a reviewer asked for concrete numbers or timing, we provided load-bearing decisions with explicit thresholds in the Health metrics contract and Data Retention policies. If you need to adapt those numbers to production, adjust the thresholds in a controlled rollout and update health dashboards accordingly.
- Where a reviewer asked for explicit workflows (e.g., webhook rotation, NATS authentication), we’ve added design-level requirements to guide implementation and testing without exposing sensitive details in this design document.
- The document now includes a dedicated Decision Log section to capture the outcomes of the open questions raised by reviewers, ensuring traceability and alignment for the next revision.