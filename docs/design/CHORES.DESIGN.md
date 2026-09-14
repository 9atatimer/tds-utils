# chores -- laptop-local herd of LLM-adjacent scheduled jobs

> **Status:** DRAFT
> **Date:** 2026-09-14
> **Authors:** Todd Stumpf (intent, `docs/concepts/lmde-tasks/`), Claude (design, on Todd's delegated authority)
> **Depends on:** [LMDE.DESIGN.md](./LMDE.DESIGN.md) (platform contract), [MACOS-APPS.DESIGN.md](./MACOS-APPS.DESIGN.md) (Dock launcher), [AGENT-NOTIFICATIONS.DESIGN.md](./AGENT-NOTIFICATIONS.DESIGN.md) (notification precedent, DRAFT)

---

## Overview

`chores` runs a herd of small, periodically invoked, LLM-adjacent jobs on the
laptop: each chore has a git-tracked definition (schedule, backend, budget,
timeout, permissions), every run leaves a record with transcript, errors and
console output kept apart, and a dashboard (CLI, TUI, menu bar, Dock) shows
what is scheduled, running, spent and broken. It exists because the only
scheduled LLM job on this machine today (`tmux_shepherd.sh` -> `log_brander`)
has no history, no budget and no way to notice when it misbehaves, and the
cloud Routines cannot run local work at all.

---

## Goals

- **Fires on schedule** -- a chore whose cron expression is due fires within
  one tick interval (60s) while the machine is awake and the scheduler is
  installed.
- **Bounded by construction** -- a run never exceeds its `timeout_sec` by
  more than the kill grace (10s), and never exceeds its token or USD budget
  by more than one backend response.
- **Complete, separated record** -- every run leaves `run.json`,
  `transcript.jsonl`, `stdout.log`, `stderr.log`, `errors.log`; `chores runs
  --json` and `chores show <id> --json` return them without reading the
  state directory by hand.
- **Missed is recorded, not replayed** -- a schedule slot that passed while
  the laptop was asleep or off produces a MISSED record and no run;
  `catch_up: true` fires exactly one run for the whole missed set.
- **One switch stops everything** -- after `chores pause`, no new run starts
  on the next tick or any later one until `chores resume`.
- **Ceilings hold** -- per-backend and global daily ceilings are never
  exceeded by more than one run's declared budget.
- **One status, three surfaces** -- CLI, TUI and menu bar render the same
  status query; the query completes in under 500ms with 1000 run records on
  disk.
- **Offline fails fast** -- a chore on a network backend fails with status
  OFFLINE within 5s when the backend is unreachable; a local-backend or
  command chore is unaffected.
- **Nothing secret persists** -- no resolved secret value appears in any
  file under the state directory (transcript, logs, run.json, ledger).
- **Swap test passes** -- adding a backend type is one adapter module plus
  one registry entry; `domain/` and `application/` are untouched.

---

## Non-Goals

- **Cloud execution** -- v1 is laptop-local. Cloud Routines stay in
  tds-internal with their own runner.
- **Filesystem or network sandboxing** -- v1 isolation is process-level:
  chosen `cwd`, explicit environment, timeout, kill. Confinement beyond that
  (sandbox-exec, containers, network deny) is a Future Consideration.
- **Multi-turn tool loops on HTTP backends** -- Ollama and gateway chores are
  single-turn completions. Agentic runs with tools go through the
  `claude-cli` backend, which already owns that loop.
- **Editing definitions from the dashboard** -- git is the editor; the
  dashboard is read-only over definitions and has run/pause/resume verbs
  only.
- **Metrics export to Grafana/OTel** -- the ledger is the record; export is
  a Future Consideration.
- **Multi-user** -- one `$HOME`, one state directory.
- **Linux GUI surfaces** -- CLI and TUI are cross-platform; menu bar and
  Dock are macOS-only.

---

## Architecture Overview

```
  definitions (git)                        state (XDG_STATE_HOME/chores)
  $CHORES_HOME/                            runs/<chore>/<run-id>/
    chores/*.md   backends.yaml              run.json transcript.jsonl
    config.yaml                              stdout.log stderr.log errors.log
        |                                  ledger.ndjson  PAUSED  last_tick
        v                                        ^
+----------------+   loads   +-------------------+------------------+
|  cli (click)   |---------->|  application                          |
|  tui (textual) |           |   tick: due -> admit -> spawn run    |
|  menu bar      |  status   |   run:  resolve -> execute -> record  |
|  (rumps)       |<----------|   status / runs / pause / install     |
+----------------+           +-------------------+------------------+
                                                 | ports only
                                                 v
                             +------------------------------------------+
                             |  domain (pure)                           |
                             |   Chore, Schedule(cron), Budget, Usage,  |
                             |   RunRecord + status FSM,                |
                             |   policies: due, admission, spend,       |
                             |   ceiling, circuit-breaker, redaction    |
                             +------------------------------------------+
                                                 ^ implemented by
                             +------------------------------------------+
                             |  adapters (edges)                        |
                             |   completion: ollama | openai-compat     |
                             |               (gateway) | claude-cli     |
                             |   store: filesystem + ndjson ledger      |
                             |   process: subprocess (clean env, kill)  |
                             |   secrets: op read     power: pmset      |
                             |   network: socket probe                  |
                             |   notify: fs queue + osascript           |
                             |   scheduler: launchd plist | systemd     |
                             +------------------------------------------+

  launchd StartInterval=60 --> `chores tick` --> spawns `chores run <name>`
```

Dependencies point inward: `cli/tui -> application -> domain`;
`adapters -> ports -> domain`. The domain names no vendor, no path, no env
var, no model id.

---

## Design

### Subsystem 1: Definitions (the git-tracked source of truth)

`$CHORES_HOME` (default `~/.config/chores`) is a directory the user keeps
under git. `chores` never writes to it. Its layout:

| Path | Holds |
|---|---|
| `chores/<name>.md` | one chore: YAML front-matter + prompt body |
| `backends.yaml` | named backends: type, endpoint, credential reference, default model, price table, daily ceiling |
| `config.yaml` | global ceilings, tick interval, missed-run grace, failure threshold |

The definition's identity for a run is the git commit of `$CHORES_HOME` at
run start (recorded in `run.json` as `definition_rev`; `dirty` when the tree
has uncommitted changes). "Compare a run to the definition that produced
it" is `git -C $CHORES_HOME show <rev>:chores/<name>.md`.

Front-matter is parsed at the edge into a `Chore` value that enforces its
invariants (valid cron, non-negative budgets, `kind` consistent with
`backend`/`command`, unknown keys rejected). A definition that fails
validation is reported by `chores validate` and skipped by `tick` with a
notification; it never crashes the tick.

`kind: prompt` sends the body to the named backend and records the
exchange. `kind: command` runs `command` (argv list) with no LLM; it is a
first-class member so workspace cleanup and the like share the record,
budget (timeout only) and dashboard.

### Subsystem 2: Scheduler (tick)

`chores tick` is stateless and idempotent, invoked every 60s by a launchd
agent (`StartInterval`) on macOS or a systemd user timer on Linux, written
by `chores install`. There is no long-lived daemon.

| Responsibility | Details |
|---|---|
| Liveness | writes `last_tick` (ISO timestamp); every surface shows scheduler staleness from it |
| Due detection | domain `due_policy(schedule, last_fired, now)`; a slot is due when the cron matches between `last_fired` and `now` |
| Missed detection | slots older than `missed_grace_sec` (default 2 ticks) are recorded MISSED, not fired; one record per chore per tick carrying the count |
| Admission | domain `admission_policy` over: global PAUSED, chore paused by breaker, chore disabled, a live RUNNING record (overlap), on-battery and `defer_on_battery`, offline and `requires_network`, ceilings from the ledger. Every refusal writes a record with its reason |
| Spawn | admitted chores start as detached `chores run <name>` processes; tick returns without waiting |
| Exclusion | one tick at a time via a lock in the state directory; a second tick exits 0 |

### Subsystem 3: Runner (run)

`chores run <name>` executes one chore end to end and owns its record.

| Responsibility | Details |
|---|---|
| Resolve | load `Chore` + backend; resolve secret references through `SecretsPort` at start; build the explicit environment (nothing inherited except `PATH`, `HOME`, `LANG`, plus declared `env` and resolved `secrets`) |
| Execute prompt | `CompletionPort.complete(request)` with `timeout_sec`, `max_output_tokens` derived from the token budget; one response |
| Execute command / claude-cli | `ProcessPort.run(argv, cwd, env, timeout)`; SIGTERM at timeout, SIGKILL after 10s grace; stdout and stderr captured to separate files |
| Enforce | domain `spend_policy(usage, budget)` after every response; TIMED_OUT / BUDGET_EXCEEDED are terminal statuses, never exceptions swallowed |
| Record | `RunStorePort` writes `run.json` on every status change, appends transcript lines as they happen, appends one ledger row at the terminal status |
| Redact | domain `redact(text, secrets)` runs over every byte before it reaches the store |
| Breaker | on a terminal failure, `circuit_breaker(recent_runs, threshold)` may pause the chore; it posts a notification either way |

### Subsystem 4: Backends (the completion seam)

One port, `CompletionPort`: `complete(CompletionRequest) -> CompletionResponse
| CompletionError`. Request carries prompt, model, `timeout_sec`,
`max_output_tokens`; response carries text, `tokens_in`, `tokens_out`,
`usd` (or `None` when the backend cannot price), provider, model, latency.
Errors are typed (`Unreachable`, `Unauthorized`, `RateLimited`, `Timeout`,
`ModelNotFound`) so the runner maps them to statuses without vendor knowledge.

| Backend type | Mechanism | Usage source | USD source |
|---|---|---|---|
| `ollama` | HTTP to a local Ollama | response counts | none (local) |
| `openai-compat` | HTTP to an OpenAI-compatible endpoint, one adapter for the family; the Cloudflare AI Gateway is the first instance | response `usage` | backend price table by model, else `None` |
| `claude-cli` | subprocess `claude -p --output-format json`, `--max-turns`, `--allowedTools`, clean env, `cwd` | reported usage | reported cost, marked `billing: subscription` |

Backend config supplies every volatile value: base URL, auth header name,
credential reference, default model, prices, ceiling. `requires_network`
defaults from type (`ollama` false, others true) and is overridable.
The `openai-compat` adapter never learns the gateway's account path; it is
part of the configured base URL.

### Subsystem 5: Guarding (budgets, ceilings, kill switch)

All decisions are domain policies with one input each:

| Policy | Inputs | Output |
|---|---|---|
| `spend_policy` | `Usage`, `Budget` | CONTINUE / STOP(reason) |
| `ceiling_policy` | ledger rows in the last 24h, backend ceiling, global ceiling, this chore's declared budget | ADMIT / REFUSE(reason) -- refuses when spent + declared budget would cross the ceiling |
| `circuit_breaker` | last N terminal statuses, threshold | KEEP / PAUSE |
| `due_policy` | schedule, last fired, now, grace | FIRE / MISSED(n) / NOT_DUE |
| `admission_policy` | the flags in Subsystem 2 | ADMIT / SKIP(reason) |

Budget denominations: tokens (always), USD (when priced), turns
(`claude-cli`), seconds (always). A chore declares any subset; an
undeclared dimension is unbounded for that chore but still counted toward
ceilings.

`chores pause [reason]` writes `PAUSED` in the state directory; presence
gates admission (contents are the reason shown on the dashboard).
`chores kill <run-id>` signals the recorded pid. `chores resume [chore]`
clears the global sentry or a breaker pause.

### Subsystem 6: Status surfaces

One application query, `status()`, returns a `StatusView`: per chore --
name, enabled, paused-by, schedule, next due, last run (status, ended,
usage), running now (run id, started); totals -- usage today per backend
and overall, ceilings and remaining; scheduler `last_tick` and staleness;
unread notifications. Every surface renders that value and nothing else:

| Surface | Mechanism | Verbs |
|---|---|---|
| `chores status` | table or `--json` | -- |
| `chores ui` | Textual TUI, refreshes every 5s from `status()` | run now, pause/resume, open run record, dismiss notification |
| `chores-monitor` | rumps menu-bar item, same mould as `skills-drift-monitor`; icon shape+color: quiet when green, warning when any chore failed, breaker-paused, or the scheduler is stale | open the TUI in a terminal, pause/resume |
| Dock | `macos/apps/chores/` via `mkmacapp`, opens a terminal running `chores ui` | -- |

Staleness rule: `last_tick` older than 3 tick intervals renders as
"scheduler stale since <time>" on every surface; a missing scheduler
install renders as "not installed".

### Subsystem 7: Notifications

`chores notify "<text>"` from inside a run (the run id is in the child's
environment) or from any shell appends a row to `notifications.ndjson`
(`ts, run_id, chore, level, text, read`). The runner posts on breaker
pause, BUDGET_EXCEEDED, TIMED_OUT, OFFLINE and validation failure. The
TUI and menu bar show unread rows; `chores notify --dismiss <id>` marks
read. On macOS, level `alert` additionally raises a system notification
through the `NotifierPort`'s osascript adapter. No bus: the queue is the
file; the AGENT-NOTIFICATIONS design's fallback shape is the whole design
here.

---

## State Machine

### Run

```
              +---------+
  tick admits |         |  spawned
  ----------->| PENDING |----------+
              +---------+          v
                              +---------+
                              | RUNNING |
                              +----+----+
        +--------+--------+-------+-------+-----------+----------+
        v        v        v       v       v           v          v
   SUCCEEDED  FAILED  TIMED_OUT BUDGET_  KILLED    OFFLINE   INTERRUPTED
                                EXCEEDED
```

| From | To | Trigger | Condition |
|---|---|---|---|
| PENDING | RUNNING | run process starts | record written with pid |
| RUNNING | SUCCEEDED | completion returned / exit 0 | spend_policy CONTINUE |
| RUNNING | FAILED | non-zero exit / typed error other than below | -- |
| RUNNING | TIMED_OUT | `timeout_sec` elapsed | process signalled |
| RUNNING | BUDGET_EXCEEDED | spend_policy STOP | -- |
| RUNNING | KILLED | `chores kill` | -- |
| RUNNING | OFFLINE | `Unreachable` from a network backend | `requires_network` |
| RUNNING | INTERRUPTED | runner process died (sleep, crash) | detected by the next tick: pid gone, no terminal status |

Non-run outcomes written by tick, terminal on creation: MISSED, DEFERRED
(battery), SKIPPED_OVERLAP, SKIPPED_PAUSED, SKIPPED_CEILING, SKIPPED_OFFLINE,
INVALID (definition failed validation).

### Chore

```
  ENABLED <-----> DISABLED (definition `enabled: false`)
     |  breaker PAUSE / `chores pause <chore>`
     v
  PAUSED_BY_BREAKER ---- `chores resume <chore>` ----> ENABLED
```

Global PAUSED overlays every chore and is not a chore state.

---

## Data Model

Definition front-matter (`chores/<name>.md`):

```
name            string, unique, [a-z0-9-]
description     string, optional
schedule        5-field cron, local time
enabled         bool, default true
kind            prompt | command
backend         name in backends.yaml (prompt only)
model           string, optional override of the backend default
command         argv list (command only; also used by claude-cli as extra args)
cwd             path, default $HOME
timeout_sec     int > 0, default 600
budget          {tokens?: int, usd?: float, turns?: int}
env             map of explicit environment
secrets         map ENV_NAME -> credential reference (resolved at run start)
allowed_tools   list (claude-cli only)
defer_on_battery bool, default false
requires_network bool, default from backend type
catch_up        bool, default false
notify_on       list of terminal statuses, default [FAILED, TIMED_OUT, BUDGET_EXCEEDED, OFFLINE]
```

Body: the prompt (kind prompt) or unused (kind command).

Run record (`run.json`):

```
run_id          <chore>-<UTC yyyymmddThhmmss>-<4 hex>
chore           name
definition_rev  git sha of $CHORES_HOME, or "<sha>-dirty", or "untracked"
status          enum above
reason          string, set on every non-SUCCEEDED status
started, ended  ISO 8601 UTC
pid             int while RUNNING
backend, model  strings (prompt only)
usage           {tokens_in, tokens_out, usd?, turns?, seconds}
exit_code       int (command / claude-cli)
```

Ledger (`ledger.ndjson`, append-only, one row per terminal status, schema
key `chores/v1`): the run record flattened plus `schema: chores/v1`. It is
the input to `ceiling_policy` and to any later analysis.

State directory (`$XDG_STATE_HOME/chores`, mode 0700): `runs/`, `ledger.ndjson`,
`notifications.ndjson`, `last_tick`, `PAUSED`, `paused/<chore>`, `tick.lock`.

---

## Data Warehouse

`ledger.ndjson` is the laptop-side cousin of the fleet's R2 ledgers
(template-tools `docs/design/ARCHITECTURE.DATA-WAREHOUSE.md`): append-only
NDJSON, one row per terminal event, schema-versioned key, no source content
(prompts and transcripts stay in the run directory, the ledger carries
counts and statuses). Nothing leaves the laptop in v1; a mirror to an R2
`chores-ledger` bucket is a Future Consideration and would carry the same
rows.

---

## Security Considerations

- **Definitions are trusted input** -- the author is the machine's owner;
  `chores` does not defend against a hostile definition. It does reject an
  invalid one.
- **No inherited environment** -- a run's environment is built explicitly
  (template-tools lesson: a subprocess LLM transport must not inherit the
  parent env). `PATH` is the launchd-safe fixed list plus `~/.local/bin`.
- **Secrets resolve late and never persist** -- credential references are
  resolved at run start through `SecretsPort`; the resolved values are the
  redaction set for every byte written by the run. `run.json` stores the
  reference, never the value.
- **Model output is data** -- `chores` never executes text a backend
  returned. Agentic behaviour exists only inside `claude-cli`, bounded by
  the definition's `allowed_tools`, `cwd`, `--max-turns` and `timeout_sec`.
- **State directory is 0700** -- transcripts can contain anything the
  prompt saw.
- **Runaway spend** -- three independent bounds: per-run budget, per-backend
  daily ceiling, global daily ceiling; plus the global PAUSED sentry and
  the breaker. A missing price table makes USD unbounded for that backend
  and the dashboard says so.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Name | `chores` | "Tasks" collides with the todo-plan `tasks/` tree and `gadmin task`; "herd" collides with Laravel Herd's CLI. Chosen on Todd's delegated authority (session 2026-09-14) |
| Home repo and language | tds-utils, Python 3.11+ package `chores/` with `bin/chores` | LMDE tool; Python is Adopt; goldfish and the monitors set the precedent |
| Scheduling mechanism | launchd `StartInterval` (systemd timer on Linux) invoking a stateless `chores tick`; chores own due/missed logic | crontab has a barren env and no notion of a missed slot; a daemon is fragile across sleep; per-chore plists multiply install state |
| Cron evaluation | own 5-field matcher in `domain/` | bounded (fields, ranges, steps, lists); keeps the schedule a pure value; croniter rejected below |
| Definition shape | YAML front-matter + prompt body, one file per chore | mirrors the Routines specs so the two kinds of scheduled LLM job read alike; body stays a verbatim prompt |
| Definition history | the user's `$CHORES_HOME` git repo; `definition_rev` recorded per run | git already is the history; `chores` never writes definitions |
| Run store | filesystem directory per run + append-only NDJSON ledger | grep/jq/DuckDB-queryable, no schema migration, matches the fleet ledger shape; SQLite rejected below |
| LLM backend axis -> `CompletionPort` | three adapters: `ollama`, `openai-compat`, `claude-cli`; model id, URL, header, credential all edge config | Swap test; the gateway is an instance of `openai-compat`, not a type |
| Budget denomination | tokens always; USD when a price table exists; turns for claude-cli; seconds always | the fleet already disagrees (designomatic USD, ci.magic turns) and subscription calls have no price; the policy takes whatever dimensions are declared |
| Ceilings | 24h rolling window computed from the ledger | no extra counter to drift; the ledger is already the record |
| Kill switch | presence-gated `PAUSED` file | the `NO.RELEASE` mould: fails closed on the most obvious way to write one |
| Missed runs | recorded, never replayed; `catch_up` fires one run | Todd's degrading story: "reported, not all fired at once" |
| Process isolation | explicit env, `cwd`, timeout, SIGTERM then SIGKILL | the only isolation available without root or a container; stated as the v1 sandbox |
| Status surfaces | one `status()` query; CLI, Textual TUI, rumps menu bar, mkmacapp Dock tile | the skills-drift precedent: one core, thin consumers |
| Notifications | NDJSON queue file; osascript for alerts | single machine; AGENT-NOTIFICATIONS' fallback path is sufficient and has no daemon |
| Secrets | credential references resolved via `op read` at run start; values redacted from every artifact | 1Password is the only sanctioned source (LMDE contract) |
| Radar proposal | **Textual** -> Trial (Python TUI; first consumer chores) | no TUI framework on any ring; Textual is the maintained Python option and pairs with the Adopt toolchain |
| Radar proposal | **PyYAML** -> Adopt (front-matter and config parsing) | the fleet's YAML front-matter convention needs a parser; stdlib has none |
| Radar proposal | **rumps** -> Adopt (macOS menu bar), recording existing use by two monitors | already in use with no row |
| Radar proposal | **croniter** -> not added | see Rejections |
| Approval | marked APPROVED by Claude on Todd's explicit delegation ("fill in my shoes for those decisions", 2026-09-14) | recorded so the status transition has a human authorization behind it |

---

## Open Questions

- **Q1 -- claude-cli cost semantics.** `claude -p` reports `total_cost_usd`
  even on a subscription. Whether to count it toward USD ceilings (as an
  opportunity-cost proxy) or only toward turn ceilings is left to the first
  month of ledger data; v1 records it and counts it, marked `subscription`.
- **Q2 -- gateway-side accounting.** The Cloudflare AI Gateway meters cost
  centrally; v1 prices locally from the backend table. Reconciling against
  the gateway's own numbers is unmeasured.
- **Q3 -- INTERRUPTED detection after sleep.** macOS may keep a run process
  alive across sleep; the run then finishes late rather than interrupted.
  Whether that late finish should count as TIMED_OUT (wall clock) or
  SUCCEEDED (process clock) is undecided; v1 uses wall clock.

---

## Rejections

- **A real crontab** -- launchd-spawned and cron-spawned processes get a
  barren environment (TODO_PLAN lesson on `.zshenv`), and cron has no
  record of a missed slot; both are the problems this tool exists to fix.
- **One launchd `StartCalendarInterval` plist per chore** -- N install
  artifacts to keep in step with N definitions; missed-slot knowledge still
  absent.
- **A long-lived daemon** -- sleep/wake and crash recovery become the
  daemon's problem; a 60s stateless tick has none of it.
- **croniter** -- a dependency for a bounded matcher the domain must own
  anyway to stay vendor-free; revisit if `L`/`W`/`#` syntax is ever needed.
- **SQLite run store** -- no radar row, one more thing to migrate, and every
  v1 query is a scan over a few thousand rows; revisit at transitive or
  cross-month analytics.
- **Grafana as the dashboard** -- needs the kind cluster up; not "reachable
  from the Dock in one click".
- **NATS for notifications** -- a bus for one producer and two readers on
  one machine; the file queue is the AGENT-NOTIFICATIONS fallback path
  already designed.
- **Unifying with cloud Routines** -- the Routines API cannot set prompts
  or tools; a shared definition would promise a round-trip it cannot keep.
  The spec *shape* is shared; the systems are not.
- **A Swift `NSStatusItem` app** -- the rumps mould exists twice already.
- **A web dashboard** -- ORCHESTRATOR.DESIGN.md's non-goal holds here too:
  terminal first.
- **A `SchedulerPort` seam** -- the launchd/systemd difference is one
  install-time template each; the tick itself is scheduler-agnostic, so a
  runtime port would be ceremony.
- **Templating in prompt bodies** -- the body is verbatim, like a Routine
  prompt; a chore that needs computed input is a `command` chore that
  builds it.

---

## Future Considerations

- **Ledger mirror to R2** -- same rows, `chores-ledger` bucket, once the
  fleet warehouse gains a laptop producer.
- **OTel export** -- emit `gen_ai` usage spans so runs appear on the
  existing Grafana token panels.
- **Real sandboxing** -- sandbox-exec profiles or a container runner behind
  `ProcessPort` once a chore needs to run untrusted code.
- **Multi-turn HTTP chores** -- a tool loop over `openai-compat` if a
  gateway model is ever the right agent.
- **Cloud chores** -- a runner that targets the Routines API from the same
  definition shape, if the API grows prompt and tool parameters.

---

## Related Documents

- [LMDE.DESIGN.md](./LMDE.DESIGN.md) -- platform contract; `op` and Ollama are Adopted components
- [MACOS-APPS.DESIGN.md](./MACOS-APPS.DESIGN.md) -- the Dock launcher this reuses
- [AGENT-NOTIFICATIONS.DESIGN.md](./AGENT-NOTIFICATIONS.DESIGN.md) -- notification precedent; this design uses only its fallback path
- `docs/concepts/lmde-tasks/` -- the phase 1 concept this converts (non-binding)
- tds-internal `ops/claude-code/routines/README.md` -- the cloud sibling's spec shape
- template-tools `docs/design/ARCHITECTURE.DATA-WAREHOUSE.md` -- the ledger shape this mirrors
- `lmde/TECH_RADAR.md` -- human-maintained; the rows proposed above are for Todd to add
- No `docs/arch/` exists in tds-utils; the as-built for this tool is written at release (phase 7a) as its first entry
