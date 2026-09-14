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
  one tick interval while the machine is awake and the scheduler is
  installed.
- **Bounded by construction** -- a run's process group is gone within the
  kill grace after `timeout_sec`; a prompt run never exceeds its token or USD
  budget by more than one backend response; an agent run is bounded during
  the run by turns and seconds and its token and USD usage is verified
  against the budget when it ends.
- **Complete, separated record** -- every run leaves `definition.md`,
  `run.json`, `transcript.jsonl`, `stdout.log`, `stderr.log`, `errors.log`;
  `chores runs --json` and `chores show <id> --json` return them without
  reading the state directory by hand.
- **Missed is recorded, not replayed** -- a schedule slot that passed while
  the laptop was asleep or off produces a MISSED record and no run;
  `catch_up: true` fires exactly one run for the whole missed set.
- **One switch stops everything** -- after `chores pause`, no run starts by
  any path (tick, `chores run`, the TUI) until `chores resume`.
- **Ceilings hold** -- a chore is admitted only when its declared budget fits
  under every ceiling that applies to it (chore, backend, global), so no
  ceiling is exceeded by more than one admitted run's declared budget.
- **One status, three surfaces** -- CLI, TUI and menu bar render the same
  status query; the query completes in under 500ms with 1000 run records on
  disk.
- **Offline fails fast** -- a chore on a network backend fails with status
  OFFLINE within 5s when the backend is unreachable; a local-backend or
  command chore is unaffected.
- **Nothing secret persists** -- no resolved secret value, verbatim or in its
  JSON-string-escaped or URL-encoded form, appears in any file under the
  state directory.
- **Swap test passes** -- adding a backend type is one adapter module plus
  one registry entry; `domain/` and `application/` are untouched.

---

## Non-Goals

- **Cloud execution** -- v1 is laptop-local. Cloud Routines stay in
  tds-internal with their own runner.
- **Filesystem or network sandboxing** -- v1 isolation is process-level:
  chosen `cwd`, explicit environment, process-group timeout and kill. A
  tool-enabled agent run can touch anything the user can, including this
  tool's own files; v1 makes that detectable (Security Considerations),
  not impossible. Confinement is a Future Consideration.
- **In-run misbehaviour detection** -- the breaker acts across runs; nothing
  judges a run's content while it is happening. The concept's aspiration
  stays aspirational.
- **Showing what a run changed on disk** -- needs the sandbox above.
- **Multi-turn tool loops on HTTP backends** -- Ollama and gateway chores are
  single-turn completions. Agentic runs go through an agent backend, which
  owns its own loop.
- **A windowed GUI dashboard** -- "GUI" in v1 is a menu-bar item and a Dock
  tile that opens the TUI in a terminal, per MACOS-APPS.DESIGN.md's rule
  that anything needing a window is a terminal program. The concept's
  "works as GUI or TUI" is met by that reading and no other.
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
  definitions (git)                        state (XDG_STATE_HOME/chores, 0700)
  $CHORES_HOME/                            runs/<chore>/<run-id>/
    chores/*.md   backends.yaml              definition.md run.json
    config.yaml                              transcript.jsonl stdout.log
        |                                    stderr.log errors.log
        v                                  ledger.ndjson notifications.ndjson
+----------------+   loads   +--------------+  PAUSED paused/<chore> last_tick
|  cli (click)   |---------->|  application |<---------------------+
|  tui (textual) |           |   tick: due -> admit -> spawn run   |
|  menu bar      |  status   |   run:  admit -> resolve -> execute |
|  (rumps)       |<----------|         -> record                   |
+----------------+           |   status / runs / pause / install   |
                             +---------------+---------------------+
                                             | ports only
                                             v
                             +------------------------------------------+
                             |  domain (pure)                           |
                             |   Chore, Schedule(cron), Budget, Usage,  |
                             |   Ceiling, RunRecord + status FSM,       |
                             |   policies: due, admission, spend,       |
                             |   ceiling, circuit-breaker, redaction    |
                             +------------------------------------------+
                                             ^ implemented by
                             +------------------------------------------+
                             |  adapters (edges)                        |
                             |   completion: ollama | openai-compat     |
                             |   agent:      claude-cli                 |
                             |   store: filesystem + ndjson ledger      |
                             |   process: subprocess (session, kill)    |
                             |   secrets: op read     power: pmset      |
                             |   network: socket probe                  |
                             |   notify: fs queue + osascript           |
                             +------------------------------------------+

  install-time only (no runtime port): `chores install` writes a launchd
  StartInterval agent (macOS) or a systemd user timer (Linux) that runs
  `chores tick` every tick interval; tick spawns `chores run <name>`.
```

Dependencies point inward: `cli/tui -> application -> domain`;
`adapters -> ports -> domain`. The domain names no vendor, no path, no env
var, no model id, no backend type.

---

## Design

### Subsystem 1: Definitions (the git-tracked source of truth)

`$CHORES_HOME` (default `~/.config/chores`) is a directory the user keeps
under git. `chores` never writes to it. Its layout:

| Path | Holds |
|---|---|
| `chores/<name>.md` | one chore: YAML front-matter + prompt body |
| `backends.yaml` | named backends: type, endpoint, credential reference, default model, price table, rolling-24h ceiling |
| `config.yaml` | global rolling-24h ceilings, tick interval, missed-run grace, failure threshold, retention, subscription-USD counting |

Every run snapshots the definition file it ran as `definition.md` in the
run directory and records `definition_rev` (the `$CHORES_HOME` git commit,
suffixed `-dirty` when the tree had uncommitted changes, or `untracked`).
"Compare a run to the definition that produced it" is a diff between two
snapshots; the rev is for finding the commit, not for reconstructing the
file.

Front-matter is parsed at the edge into a `Chore` value that enforces its
invariants (Data Model). `chores validate` reports every violation;
`tick` records INVALID for a chore that fails and never crashes.

Three kinds, each bound to one execution port:

| `kind` | Port | What runs |
|---|---|---|
| `prompt` | `CompletionPort` | the body, single-turn, to a completion backend |
| `agent` | `AgentPort` | the body as the task for an agentic backend in a workspace, with a tool allowlist and a turn budget |
| `command` | `ProcessPort` | `command` argv, no LLM; a first-class member so cleanup jobs share the record, timeout and dashboard |

A `backends.yaml` entry names a `type`; the registry maps a type to an
adapter and to the port it implements, and validation rejects a chore whose
kind does not match its backend's port. No backend type name appears in
the domain.

`chores run <name> --dry-run` prints the resolved plan -- backend, model,
port, `cwd`, environment variable names, secret reference names (never
values), argv, budget, applicable ceilings and the admission decision --
and executes nothing.

### Subsystem 2: Scheduler (tick)

`chores tick` is stateless and idempotent, invoked every tick interval
(default 60s) by the installed launchd agent or systemd timer. There is no
long-lived daemon.

| Responsibility | Details |
|---|---|
| Exclusion | an OS-held advisory lock (`flock`) on `tick.lock`, released when the process dies; a second concurrent tick exits 0 without acting |
| Liveness | writes `last_tick`; every surface shows scheduler staleness from it |
| First sight | a chore seen for the first time (new file, renamed) has its window opened at that tick; it fires at its next slot and never catches up across the gap before it was seen |
| Due detection | domain `due_policy(schedule, window_start, now, grace)`; a slot is due when the cron matches between `window_start` (the last fired or skipped slot, or first sight) and `now`, evaluated on the local wall clock. A spring-forward slot that never exists fires once at the first instant after the gap; a fall-back slot that occurs twice fires once, keyed by its wall-clock label |
| Missed detection | slots older than `missed_grace_sec` (default two tick intervals) are recorded MISSED, not fired; one record per chore per tick carrying the count; `catch_up: true` fires one run for the set |
| Admission | domain `admission_policy` (Subsystem 5); every refusal writes a record with its reason. A `defer_on_battery` chore refused for battery keeps its slot: the window does not advance, and the next tick on AC power fires one run |
| Interrupted | a RUNNING record whose `pid` is gone or whose process start time differs from the recorded one, and a PENDING record older than one tick interval with no RUNNING transition, become INTERRUPTED |
| Spawn | admitted chores start as detached `chores run <name>` processes; tick returns without waiting |

### Subsystem 3: Runner (run)

`chores run <name>` executes one chore end to end and owns its record. It
is the only path that starts a run, so admission lives here as well as in
tick.

| Responsibility | Details |
|---|---|
| Admit | `admission_policy` again with live state. `--force` overrides overlap, battery and offline refusals only; the global PAUSED sentry, a breaker pause and every ceiling are never overridable from the command line |
| Resolve | load the `Chore` and its backend; snapshot `definition.md`; resolve secret references through `SecretsPort` under `secret_timeout_sec` (default 30s) so a locked vault fails the run as FAILED with reason `secret unavailable: <ref name>` instead of burning `timeout_sec` |
| Environment | built explicitly: `PATH` inherited from the runner (whose launchd wrapper starts through the login shell so the tiered `tds_path_apply` PATH is in effect), `HOME`, `LANG`, the declared `env`, resolved `secrets`, `CHORES_RUN_ID`, `CHORES_CHORE`, `CHORES_BUDGET_TOKENS` / `_USD` / `_TURNS` / `_SECONDS` (declared values, so an agent or command can read what it has), and `CHORES_SECRET_NAMES` (the names, for `chores notify`'s redaction). Nothing else is inherited |
| Execute prompt | `CompletionPort.complete(request)` with `timeout_sec` and `max_output_tokens` derived from the token budget; one response |
| Execute agent | `AgentPort.run(task)` with the body, `cwd`, tool allowlist, `max_turns`, `timeout_sec`, environment; the adapter owns the loop and reports usage |
| Execute command | `ProcessPort.run(argv, cwd, env, timeout)` |
| Process bound | every child starts in its own session (process group); at `timeout_sec` the whole group gets SIGTERM, then SIGKILL after `kill_grace_sec` (default 10s); `chores kill <run-id>` signals the same group. `run.json` records `pid`, `pgid` and the process start time |
| Enforce | domain `spend_policy(usage, budget)` after every response and at the end of an agent run; TIMED_OUT / BUDGET_EXCEEDED are terminal statuses, never swallowed exceptions |
| Record | `RunStorePort` writes `run.json` on every status change, appends transcript lines as complete JSON objects (one per line, so a value cannot straddle two lines), appends one ledger row at the terminal status. Usage includes wall `seconds`, child `cpu_seconds` (rusage) and `disk_bytes` of the run directory; a writer that reaches `max_run_dir_bytes` stops writing, marks the record `truncated`, and does not change the status |
| Redact | domain `redact(text, secrets)` covers each resolved value verbatim and in JSON-string-escaped and URL-encoded form, applied to every byte before it reaches the store. Encodings a tool invents beyond those (base64, split tokens) are out of the claim |
| Notify | per `notify_on`; level `alert` for BUDGET_EXCEEDED and a breaker pause, `info` otherwise |
| Breaker | on a terminal failure, `circuit_breaker(recent_statuses, threshold)` may pause the chore; it posts an `alert` when it does |

### Subsystem 4: Backends (the two execution seams)

`CompletionPort`: `complete(CompletionRequest) -> CompletionResponse |
CompletionError`. Request: prompt, model, `timeout_sec`,
`max_output_tokens`. Response: text, `tokens_in`, `tokens_out`, `usd` (or
`None` when unpriced), provider, model, latency, `billing` (`metered` or
`subscription`).

`AgentPort`: `run(AgentTask) -> AgentResult | AgentError`. Task: body,
`cwd`, `allowed_tools`, `max_turns`, `timeout_sec`, environment. Result:
final text, transcript events, `tokens_in`, `tokens_out`, `usd`, `turns`,
`billing`, exit code.

Errors are typed on both ports (`Unreachable`, `Unauthorized`,
`RateLimited`, `Timeout`, `ModelNotFound`, `SecretUnavailable`) so the
runner maps them to statuses without vendor knowledge.

| Backend type | Port | Mechanism | Usage source | USD source |
|---|---|---|---|---|
| `ollama` | completion | HTTP to a local Ollama | response counts | none (local) |
| `openai-compat` | completion | HTTP to an OpenAI-compatible endpoint; one adapter for the family, configured by base URL, auth header name and credential reference. The Cloudflare AI Gateway is the first instance; its account path is part of the configured base URL and the adapter never learns it | response `usage` | backend price table by model, else `None` |
| `claude-cli` | agent | the Claude Code CLI in headless mode with JSON output, a turn cap and the tool allowlist. Load-bearing isolation: the operator's global MCP servers and settings sources are disabled on every invocation (`--strict-mcp-config` with an empty MCP config and no setting sources -- template-tools TODO_PLAN lesson 19). `HOME` is required because the subscription credential is keychain-bound; that credential is never written by the run and is outside the redaction set | reported usage and turns | reported cost, `billing: subscription` |

Backend config supplies every volatile value. `requires_network` defaults
from type (`ollama` false, others true) and is overridable. A backend with
a USD ceiling and no price table is INVALID at validation.

### Subsystem 5: Guarding (budgets, ceilings, kill switch)

All decisions are domain policies with one input each:

| Policy | Inputs | Output |
|---|---|---|
| `spend_policy` | `Usage`, `Budget` | CONTINUE / STOP(reason) |
| `ceiling_policy` | ledger rows from the rolling 24h window, the chore's ceiling, the backend's ceiling, the global ceiling, the chore's declared budget | ADMIT / REFUSE(reason); refuses when spent plus declared budget would cross any applicable ceiling in any dimension; the smallest ceiling wins |
| `circuit_breaker` | last N terminal statuses, threshold | KEEP / PAUSE |
| `due_policy` | schedule, window start, now, grace | FIRE / MISSED(n) / NOT_DUE |
| `admission_policy` | global PAUSED, breaker pause, disabled, live RUNNING record, on battery and `defer_on_battery`, offline and `requires_network`, the ceiling verdict, `--force` | ADMIT / SKIP(reason) |

Dimensions: tokens, USD, turns (agent), seconds. A chore declares a
`budget` in any subset; **a chore must declare every dimension in which a
ceiling applies to it** (chore, backend or global), and validation rejects
one that does not -- so an undeclared dimension is never an unbounded
addend. Ceilings are per rolling 24h in tokens and USD (backend, global)
plus the chore's own. `billing: subscription` rows count toward token and
turn ceilings and, by default, not toward USD ceilings
(`count_subscription_usd: false`).

`chores pause [reason]` writes `PAUSED` in the state directory; presence
gates admission on every path (contents are the reason shown on the
dashboard). `chores resume [chore]` clears the global sentry or a breaker
pause. `chores kill <run-id>` signals the run's process group.

### Subsystem 6: Status surfaces

One application query, `status()`, returns a `StatusView`: per chore --
name, enabled, paused-by, schedule, next due, last run, last success, last
failure (each with status, ended, usage), running now (run id, started);
totals -- usage in the rolling 24h per backend and overall, ceilings and
remaining; scheduler `last_tick`, staleness and installed state; unread
notifications. Every surface renders that value and nothing else:

| Surface | Mechanism | Verbs |
|---|---|---|
| `chores status` | table or `--json` | -- |
| `chores ui` | Textual TUI over `status()`, periodically refreshed | run now, pause/resume, open run record, dismiss notification |
| `chores-monitor` | rumps menu-bar item, same mould as `skills-drift-monitor`; icon shape+color: quiet when green, warning when any chore's last run failed, a breaker pause is active, or the scheduler is stale | open the TUI in a terminal, pause/resume |
| Dock | `macos/apps/chores/` via `mkmacapp`, opens a terminal running `chores ui` | -- |

Staleness rule: `last_tick` older than three tick intervals renders as
"scheduler stale since <time>" on every surface; no installed agent or
timer renders as "not installed".

### Subsystem 7: Notifications

`chores notify "<text>"` appends a row to `notifications.ndjson` (`ts,
run_id, chore, level, text, read`) through the store, after redacting the
values of every environment variable named in `CHORES_SECRET_NAMES` -- so
a child run posting from inside its environment cannot leak what it was
given. The runner posts for each terminal status in the chore's
`notify_on`, and tick posts for INVALID definitions and breaker pauses
regardless of any chore's setting. The TUI and menu bar show unread rows;
`chores notify --dismiss <id>` marks read. On macOS a level `alert` row
additionally raises a system notification through the `NotifierPort`'s
osascript adapter, which passes the text as a script argument and never
interpolates it into the script. No bus: the queue is the file; the
AGENT-NOTIFICATIONS design's fallback shape is the whole design here.

### Subsystem 8: Retention

`config.yaml` `retention_days` (default 90) lets `chores prune` delete run
directories older than that; the ledger and notifications are never
pruned. `chores status` shows the state directory's size.

---

## State Machine

### Run

```
              +---------+
  admitted    |         |  run process starts
  ----------->| PENDING |----------+
              +----+----+          v
                   |          +---------+
                   |          | RUNNING |
                   |          +----+----+
                   |    +------+---+----+--------+----------+---------+
                   |    v      v        v        v          v         v
                   | SUCCEEDED FAILED TIMED_OUT BUDGET_  KILLED    OFFLINE
                   |                            EXCEEDED
                   +----------------> INTERRUPTED <---------------------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| PENDING | RUNNING | run process starts | record carries pid, pgid, process start time |
| PENDING | INTERRUPTED | next tick | older than one tick interval, never RUNNING |
| RUNNING | SUCCEEDED | completion returned / exit 0 | spend_policy CONTINUE |
| RUNNING | FAILED | non-zero exit, `SecretUnavailable`, or any typed error not mapped below | -- |
| RUNNING | TIMED_OUT | `timeout_sec` elapsed | process group signalled |
| RUNNING | BUDGET_EXCEEDED | spend_policy STOP | -- |
| RUNNING | KILLED | `chores kill` | -- |
| RUNNING | OFFLINE | `Unreachable` from a network backend | `requires_network` |
| RUNNING | INTERRUPTED | next tick | pid gone or process start time mismatch, no terminal status |

Non-run outcomes written by tick, terminal on creation: MISSED, INVALID,
SKIPPED_OVERLAP, SKIPPED_PAUSED, SKIPPED_CEILING, SKIPPED_OFFLINE,
SKIPPED_BATTERY (the slot is consumed) and DEFERRED_BATTERY (the slot is
retained; written for a `defer_on_battery` chore).

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
kind            prompt | agent | command
backend         name in backends.yaml (prompt, agent); its port must match kind
model           string, optional override of the backend default
command         argv list (command only)
cwd             path; default: a per-chore workspace under the data dir; may
                not be, contain, or be inside $CHORES_HOME or the state dir
timeout_sec     int > 0, default 600
budget          {tokens?: int, usd?: float, turns?: int}; must cover every
                dimension in which a ceiling applies to this chore
ceiling         {tokens?: int, usd?: float} per rolling 24h, optional
env             map of explicit environment
secrets         map ENV_NAME -> credential reference (resolved at run start)
allowed_tools   list (agent only); default read-only tools; write and shell
                tools only when listed explicitly
defer_on_battery bool, default false
requires_network bool, default from backend type
catch_up        bool, default false
notify_on       list of run terminal statuses, default
                [FAILED, TIMED_OUT, BUDGET_EXCEEDED, OFFLINE, INTERRUPTED]
```

Body: the prompt or agent task (kinds prompt, agent); unused for command.

Run record (`run.json`):

```
run_id          <chore>-<UTC timestamp>-<short random suffix>
chore           name
kind            prompt | agent | command
definition_rev  git sha of $CHORES_HOME, "<sha>-dirty", or "untracked"
status          enum above
reason          string, set on every non-SUCCEEDED status
started, ended  ISO 8601 UTC
pid, pgid, process_start   while RUNNING
backend, model, billing    (prompt, agent)
usage           {tokens_in, tokens_out, usd?, turns?, seconds, cpu_seconds, disk_bytes}
exit_code       int (command, agent)
truncated       bool
```

Ledger (`ledger.ndjson`, append-only, one row per terminal status, schema
key `chores/v1`): the run record flattened plus `schema: chores/v1`. It is
the input to `ceiling_policy` and to any later analysis.

Directories: state `$XDG_STATE_HOME/chores` (mode 0700): `runs/`,
`ledger.ndjson`, `notifications.ndjson`, `last_tick`, `PAUSED`,
`paused/<chore>`, `tick.lock`. Data `$XDG_DATA_HOME/chores/workspaces/<chore>/`
for default `cwd`.

---

## Data Warehouse

`ledger.ndjson` is the laptop-side cousin of the fleet's R2 ledgers
(template-tools `docs/design/ARCHITECTURE.DATA-WAREHOUSE.md`): append-only
NDJSON, one row per terminal event, schema-versioned key, no source content
(prompts and transcripts stay in the run directory; the ledger carries
counts and statuses). Nothing leaves the laptop in v1; a mirror to an R2
`chores-ledger` bucket is a Future Consideration and would carry the same
rows.

---

## Security Considerations

- **Definitions are trusted input; runs are not** -- the author is the
  machine's owner, so `chores` rejects an invalid definition but does not
  defend against a hostile one. A run is a different principal: it gets
  only what its definition grants.
- **No inherited environment** -- a run's environment is built explicitly
  (template-tools lesson 20). Only `PATH`, `HOME` and `LANG` cross from the
  runner.
- **The agent backend runs blind to the operator's agent config** -- global
  MCP servers and setting sources are disabled on every invocation
  (lesson 19); the tool allowlist defaults to read-only tools.
- **A tool-enabled run can reach this tool's own files** -- with write or
  shell tools listed, an agent run can edit its definition, delete `PAUSED`
  or truncate the ledger, and v1 cannot prevent it without a sandbox
  (Non-Goals). Mitigations: `cwd` may not be inside or contain
  `$CHORES_HOME` or the state directory; write and shell tools are opt-in
  per chore; `definition.md` is snapshotted before execution so a
  self-edit is visible on the next run's diff; the ledger row count is
  written to `last_tick` so a shrink is reported as a warning on every
  surface.
- **Secrets resolve late and never persist** -- credential references are
  resolved at run start through `SecretsPort` under their own timeout; the
  resolved values are the redaction set for every byte the run writes,
  including notifications posted from inside it. `run.json` stores the
  reference, never the value.
- **Model output is data** -- `chores` never executes text a backend
  returned. Agentic behaviour exists only behind `AgentPort`, bounded by
  the definition's `allowed_tools`, `cwd`, `max_turns` and `timeout_sec`.
- **Notifications are not a script surface** -- text reaches osascript as
  an argument.
- **State directory is 0700** -- transcripts can contain anything the
  prompt saw.
- **Runaway spend** -- per-run budget, chore / backend / global ceilings
  with mandatory declared dimensions, the global PAUSED sentry on every
  path, the breaker, and process-group kill. A backend that cannot price
  cannot carry a USD ceiling (INVALID), so "unbounded USD" cannot arise
  silently.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Name | `chores` | "Tasks" collides with the todo-plan `tasks/` tree and `gadmin task`; "herd" collides with Laravel Herd's CLI. Chosen on Todd's delegated authority (session 2026-09-14) |
| File name | `CHORES.DESIGN.md` | matches every sibling in this repo's `docs/design/`; the fleet rubric's `DESIGN.<name>.md` is the template-tools convention |
| Home repo and language | tds-utils, Python 3.11+ package `chores/` with `bin/chores` | LMDE tool; Python is Adopt; goldfish and the monitors set the precedent |
| Scheduling mechanism | launchd `StartInterval` (systemd timer on Linux) invoking a stateless `chores tick`; chores own due/missed logic | crontab has a barren env and no notion of a missed slot; a daemon is fragile across sleep; per-chore plists multiply install state |
| Cron evaluation | own 5-field matcher in `domain/` on the local wall clock, with the DST rules in Subsystem 2 | bounded; keeps the schedule a pure value; croniter rejected below |
| Definition shape | YAML front-matter + prompt body, one file per chore | mirrors the Routines specs so the two kinds of scheduled LLM job read alike; body stays a verbatim prompt |
| Definition history | the user's `$CHORES_HOME` git repo, plus a per-run `definition.md` snapshot | git is the history; the snapshot is what a dirty tree cannot give back |
| Run store | filesystem directory per run + append-only NDJSON ledger | grep/jq/DuckDB-queryable, no schema migration, matches the fleet ledger shape; SQLite rejected below |
| Execution seams | `CompletionPort` (single-turn) and `AgentPort` (agentic, tools, turns), plus `ProcessPort` for commands; kind selects the port, the registry maps backend type to adapter | an agentic backend does not fit a completion request; two ports keep every vendor name at the edge |
| Budget denomination | tokens, USD, turns, seconds; a chore declares every dimension a ceiling applies to | the fleet already disagrees (designomatic USD, ci.magic turns); mandatory declaration is what makes a ceiling enforceable |
| Subscription cost | recorded as reported; counts toward token and turn ceilings, not USD by default | a subscription-only user would otherwise trip USD ceilings with zero real spend |
| Ceiling window | rolling 24h, computed from the ledger, everywhere | one window, no extra counter to drift |
| Admission location | in the runner as well as tick; `--force` cannot lift PAUSED, breaker or ceilings | the kill switch has to hold on every path |
| Kill switch | presence-gated `PAUSED` file | the `NO.RELEASE` mould: fails closed on the most obvious way to write one |
| Missed runs | recorded, never replayed; `catch_up` fires one run; `defer_on_battery` retains the slot | Todd's degrading stories: "reported, not all fired at once", "defer until plugged in" |
| Process isolation | own session per child, group SIGTERM then SIGKILL, explicit env, `cwd` rule | the only isolation available without root or a container; stated as the v1 sandbox |
| Status surfaces | one `status()` query; CLI, Textual TUI, rumps menu bar, mkmacapp Dock tile | the skills-drift precedent: one core, thin consumers |
| Notifications | NDJSON queue file; osascript for alerts with argument passing | single machine; AGENT-NOTIFICATIONS' fallback path is sufficient and has no daemon |
| Secrets | credential references resolved via `op read` at run start; values redacted from every artifact | 1Password is the only sanctioned source (LMDE contract) |
| Radar proposal | **Textual** -> Trial (Python TUI; first consumer chores) | no TUI framework on any ring; Textual is the maintained Python option and pairs with the Adopt toolchain |
| Radar proposal | **PyYAML** -> Adopt (front-matter and config parsing) | the fleet's YAML front-matter convention needs a parser; stdlib has none |
| Radar proposal | **rumps** -> Adopt (macOS menu bar), recording existing use by two monitors | already in use with no row |
| Radar proposal | **croniter** -> not added | see Rejections |
| Status transitions | DRAFT -> REVIEW after the adversarial panel (2026-09-14, 25 findings, all resolved in this revision); REVIEW -> APPROVED on Todd's explicit delegation ("fill in my shoes for those decisions", same session) | the ladder is human-owned; the delegation is the human act, recorded here so the transition has an owner |

---

## Open Questions

- **Q1 -- gateway-side accounting.** The Cloudflare AI Gateway meters cost
  centrally; v1 prices locally from the backend table. Reconciling against
  the gateway's own numbers is unmeasured.
- **Q2 -- late finish after sleep.** macOS may keep a run process alive
  across sleep; the run then finishes late rather than interrupted. v1
  uses the wall clock (TIMED_OUT); whether that is the right verdict waits
  on ledger data.
- **Q3 -- locked vault at night.** `op read` from a launchd-spawned process
  with a locked vault is expected to fail fast under `secret_timeout_sec`;
  whether it can instead raise a GUI prompt on this machine is unmeasured.

---

## Rejections

- **A real crontab** -- launchd-spawned and cron-spawned processes get a
  barren environment (TODO_PLAN lesson on `.zshenv`), and cron has no
  record of a missed slot; both are the problems this tool exists to fix.
- **An off-the-shelf crontab TUI as the foundation** (crontab-ui,
  cronitor, the like) -- they edit crontab lines; none owns run records,
  budgets, transcripts or backends, which is the whole tool. Todd's "use
  one if it exists" was conditional on extensibility, and none extends to
  those.
- **One launchd `StartCalendarInterval` plist per chore** -- N install
  artifacts to keep in step with N definitions; missed-slot knowledge still
  absent.
- **A long-lived daemon** -- sleep/wake and crash recovery become the
  daemon's problem; a stateless tick has none of it.
- **croniter** -- a dependency for a bounded matcher the domain must own
  anyway to stay vendor-free; revisit if `L`/`W`/`#` syntax is ever needed.
- **SQLite run store** -- no radar row, one more thing to migrate, and every
  v1 query is a scan over a few thousand rows; revisit at transitive or
  cross-month analytics.
- **One port for every backend** -- an agentic run has a workspace, tools
  and turns that a completion request cannot carry; forcing it through one
  seam put the vendor name in the core.
- **Grafana as the dashboard** -- needs the kind cluster up; not "reachable
  from the Dock in one click".
- **NATS for notifications** -- a bus for one producer and two readers on
  one machine; the file queue is the AGENT-NOTIFICATIONS fallback path
  already designed.
- **Unifying with cloud Routines** -- the Routines API cannot set prompts
  or tools; a shared definition would promise a round-trip it cannot keep.
  The spec *shape* is shared; the systems are not.
- **A Swift `NSStatusItem` app** -- the rumps mould exists twice already.
- **A web or windowed dashboard** -- ORCHESTRATOR.DESIGN.md's non-goal and
  MACOS-APPS.DESIGN.md's rule both hold: terminal first.
- **A `SchedulerPort` seam** -- the launchd/systemd difference is one
  install-time template each; the tick itself is scheduler-agnostic, so a
  runtime port would be ceremony.
- **Templating in prompt bodies** -- the body is verbatim, like a Routine
  prompt; a chore that needs computed input is a `command` chore that
  builds it.
- **Refusing to run from a dirty `$CHORES_HOME`** -- would block the
  edit-run-edit loop the tool exists for; the snapshot makes the dirty case
  reviewable instead.

---

## Future Considerations

- **Ledger mirror to R2** -- same rows, `chores-ledger` bucket, once the
  fleet warehouse gains a laptop producer.
- **OTel export** -- emit `gen_ai` usage spans so runs appear on the
  existing Grafana token panels.
- **Real sandboxing** -- sandbox-exec profiles or a container runner behind
  `ProcessPort`/`AgentPort` once a chore needs to run untrusted code; this
  is also what would make "what did the run change" and in-run detection
  answerable.
- **Multi-turn HTTP chores** -- a tool loop over `openai-compat` if a
  gateway model is ever the right agent.
- **More agent backends** -- codex or gemini CLIs behind `AgentPort`, one
  adapter each.
- **Cloud chores** -- a runner that targets the Routines API from the same
  definition shape, if the API grows prompt and tool parameters.

---

## Related Documents

- [LMDE.DESIGN.md](./LMDE.DESIGN.md) -- platform contract; `op` and Ollama are Adopted components
- [MACOS-APPS.DESIGN.md](./MACOS-APPS.DESIGN.md) -- the Dock launcher this reuses, and the terminal-first rule
- [AGENT-NOTIFICATIONS.DESIGN.md](./AGENT-NOTIFICATIONS.DESIGN.md) -- notification precedent; this design uses only its fallback path
- `docs/concepts/lmde-tasks/` -- the phase 1 concept this converts (non-binding)
- tds-internal `ops/claude-code/routines/README.md` -- the cloud sibling's spec shape
- template-tools `docs/design/ARCHITECTURE.DATA-WAREHOUSE.md` -- the ledger shape this mirrors
- template-tools `TODO_PLAN.md` lessons 19-21 -- headless CLI agent isolation, env inheritance, subprocess timeouts
- `lmde/TECH_RADAR.md` -- human-maintained; the rows proposed above are for Todd to add
- No `docs/arch/` exists in tds-utils; the as-built for this tool is written at release (phase 7a) as its first entry
