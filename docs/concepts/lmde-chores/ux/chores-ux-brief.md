# chores -- UX design brief

You are a senior interaction designer specialising in terminal UIs and
operator dashboards. Design the user experience for `chores`, a laptop-local
scheduler for small LLM-adjacent jobs. Everything you need is in this
docket: the brief (this section), a domain reference (what the system knows
and can do), constraints, a sample data snapshot, and the user stories.

An implementation of these surfaces already exists. You are deliberately
not shown it. Do not ask for it and do not guess at it -- design from the
stories and the domain reference as if nothing had been built.

## The product in one paragraph

A developer keeps a directory of "chore" definitions in git: each is a
schedule (cron), a kind (a single LLM prompt, an agentic LLM task with
tools, or a plain shell command), a backend (local model, cloud gateway,
subscription CLI agent), a per-run budget and optional rolling-24h
ceilings. A tick fires every 60 seconds from the OS scheduler and starts
whatever is due. Every run leaves a record: status, reason, usage, and
separate transcript / stdout / stderr / errors artifacts plus a snapshot of
the definition it ran. The laptop sleeps, loses network, runs on battery;
those are expected conditions, not surprises. The operator's jobs are:
know at a glance whether anything needs them, find out why, act (run,
pause, resume, kill, dismiss), and look back over history. LLM jobs
misbehave and cost money, so "is anything burning budget or stuck" is a
first-class question.

The stories say "task"; the product is called "chores" and a task is a
"chore". Same thing.

## What to design

Four surfaces that render ONE shared status snapshot (Domain reference, 3)
and nothing else:

1. **Glance** -- a macOS menu-bar item. Answers "does anything need me?"
   without opening anything.
2. **Dashboard** -- a full-screen terminal UI. The main working surface:
   overview, drill-down into a chore and its run history, a single run's
   record and artifacts, notifications, usage against ceilings, and the
   actions.
3. **Launcher** -- a Dock tile that opens the dashboard in a terminal
   window. Design what the user sees between click and ready, and what
   happens when a dashboard is already open.
4. **CLI read output** -- the human-readable (non-JSON) text of
   `chores status`, `chores runs` and `chores show <run-id>`. Scripts use
   `--json`; you design only the text a person reads.

## Deliverables

Produce one Markdown document, ASCII only (straight quotes, `--`, `->`,
box drawing with `+ - |`; no Unicode symbols, no emoji, no images). In
this order:

1. **Mental model** -- one paragraph: the objects the operator thinks in
   and how they relate. Then the information architecture as an ASCII
   tree of screens/views and how you move between them.
2. **Attention model** -- what counts as "needs me", ranked. A table:
   condition -> severity -> where it surfaces on each of the four
   surfaces -> how it clears (self-clears, acknowledge, act). Cover every
   condition in Domain reference 5.
3. **Glance** -- the menu-bar title/icon for each attention state (use
   text glyphs; state what a real icon would depict), and the full
   dropdown menu for at least: all quiet; something failed; global pause
   active; scheduler stale or not installed. Note the menu-bar item is a
   native menu: a title with an optional icon, and a dropdown of plain
   text items, separators, submenus and checkmarks -- no custom views,
   no tables, no colour inside the menu.
4. **Dashboard** -- for every screen: an ASCII wireframe at 80x24,
   populated with the Sample snapshot (not lorem ipsum); a second
   wireframe at 160x48 for the overview and the run view at least; the
   purpose of the screen in one line; every key binding; what refreshes
   and how the user knows how fresh the data is. Include the key map as
   one table at the end.
5. **Actions** -- for each action in Domain reference 4: where it is
   invoked, what confirmation it needs (if any) and why, what the user
   sees while it is in flight, on success, and on refusal. Refusals are
   real: a run can be refused because of global pause, a breaker pause,
   a ceiling, an overlap, battery or offline, and some of those can be
   forced and some cannot. Design the refusal, not just the happy path.
6. **State catalogue** -- a wireframe or a precise description for each
   of: first launch with zero chores; not installed; scheduler stale;
   global pause; a chore paused by the breaker; an invalid definition; a
   run in progress; a run that was killed, timed out, went over budget,
   went offline, was interrupted; missed slots after sleep; battery
   deferral; a ceiling near and at exhaustion; a truncated run record;
   the ledger-shrank warning; the status snapshot itself failing to load.
7. **Run record** -- how a single run is read: header facts, then
   transcript, errors, stdout, stderr as distinct things, the definition
   snapshot it ran, and a comparison of that snapshot against another
   run's snapshot. Transcripts can be long (thousands of lines) and are
   JSON lines; say how they are presented and navigated.
8. **CLI text output** -- mock the terminal output of `chores status`,
   `chores runs --chore <name>` and `chores show <run-id>` using the
   sample data. Must be legible when piped to a file or `less`, with no
   colour.
9. **Traceability** -- a table with one row per user story (all of
   them, in the docket's order): story -> the surface(s) and element(s)
   that serve it, or "out of v1" citing the constraint in section
   "Constraints and non-goals" that excludes it, or "data gap" naming
   what the domain reference lacks.
10. **Rejected alternatives** -- the designs you considered and dropped,
    one line each with the reason.
11. **Open questions** -- only questions whose answer would change the
    design; for each, your default if nobody answers.

## Rules of engagement

- Use only data listed in the Domain reference. If a story needs
  something the reference does not have, do not invent it -- mark it as
  a data gap in the traceability table and design as if it were absent.
- Do not design editing of definitions. Git is the editor; the dashboard
  is read-only over definitions (Constraints).
- Colour may reinforce meaning, never carry it alone: every state must be
  distinguishable in monochrome (NO_COLOR, a pipe, a colour-blind
  operator). Say which text/glyph carries each state.
- Keyboard-first. Mouse is a convenience, never the only way.
- Prefer one obvious way to do each thing over several.
- The operator is one expert user on their own machine who reads logs for
  a living. Optimise for scan speed and zero ambiguity, not for
  onboarding. No tutorials, no wizards.
- Be concrete. Every screen you name gets a wireframe; every key you
  mention gets a binding; every state gets an appearance.

---

# Domain reference

## 1. Objects

**Chore** (a definition file in git; read-only to every surface):

| Field | Meaning |
|---|---|
| name | unique, `[a-z0-9-]` |
| description | optional one-liner |
| schedule | 5-field cron, local time |
| enabled | false = disabled in git; never fires |
| kind | `prompt` (one LLM call), `agent` (agentic LLM run with tools and turns), `command` (argv, no LLM) |
| backend | named backend (prompt, agent); none for command |
| model | optional override of the backend default |
| timeout_sec | wall-clock cap per run |
| budget | per run, any of: tokens, usd, turns |
| ceiling | per rolling 24h, any of: tokens, usd, turns (optional) |
| defer_on_battery | on battery, hold the slot and fire when back on AC |
| requires_network | fail fast as OFFLINE if the backend is unreachable |
| catch_up | after missed slots, fire one run for the whole missed set |
| notify_on | which terminal statuses post a notification |
| allowed_tools | agent only: the tools the agent may use |

**Backend** (config in git): name, type (local model / OpenAI-compatible
cloud gateway / subscription CLI agent), billing (`metered` or
`subscription`), optional price table, optional rolling-24h ceiling.

**Run record** (one per run or non-run outcome):

| Field | Meaning |
|---|---|
| run_id | `<chore>-<UTC timestamp>-<suffix>` |
| chore, kind | |
| status | see 2 |
| reason | set on every non-SUCCEEDED status, human-readable |
| started, ended | timestamps |
| backend, model, billing | which backend and model actually served it |
| usage | tokens_in, tokens_out, usd (may be absent), turns (agent), seconds, cpu_seconds, disk_bytes |
| exit_code | command and agent |
| definition_rev | git commit of the definitions dir, `<sha>-dirty`, or `untracked` |
| truncated | the run hit its disk cap; artifacts are incomplete |
| artifacts | `definition.md` (snapshot), `transcript.jsonl`, `stdout.log`, `stderr.log`, `errors.log` |

**Notification**: id, timestamp, run_id (optional), chore (optional),
level (`info` or `alert`), text, read. Posted by the system on configured
statuses and breaker pauses, or by a chore itself from inside a run
("3 PRs need your review"). Alerts also raise a macOS system notification.

## 2. Run statuses

Run outcomes (a run actually started):

| Status | Meaning |
|---|---|
| PENDING | admitted, process not yet started (seconds) |
| RUNNING | in progress |
| SUCCEEDED | finished within budget |
| FAILED | non-zero exit, secret unavailable, or backend error |
| TIMED_OUT | hit timeout_sec; process group killed |
| BUDGET_EXCEEDED | usage crossed the per-run budget; stopped |
| KILLED | operator killed it |
| OFFLINE | network backend unreachable; failed fast |
| INTERRUPTED | the process vanished (lid closed, crash) with no verdict |

Non-run outcomes (a slot came due and did not run), each a record with a
reason:

| Status | Meaning |
|---|---|
| MISSED | slot(s) passed while asleep/off; carries a count; never replayed unless catch_up |
| INVALID | the definition fails validation; carries every violation |
| SKIPPED_OVERLAP | previous run still going |
| SKIPPED_PAUSED | global or chore pause in effect |
| SKIPPED_CEILING | declared budget would cross a ceiling |
| SKIPPED_OFFLINE | network backend unreachable at admission |
| DEFERRED_BATTERY | on battery; slot held until AC power |

Chore states: ENABLED, DISABLED (in git), PAUSED (by the operator for this
chore, or by the circuit breaker after N consecutive failures; the reason
says which). A global pause overlays every chore and is not a chore state.

## 3. The status snapshot (the only thing surfaces render)

Computed on demand in under 500 ms with 1000 run records on disk.
Surfaces poll it; there is no push.

- `at` -- when the snapshot was taken
- `paused` -- global pause reason, or none
- per chore: name, kind, enabled, paused_by (reason or none), schedule,
  next_due, backend, invalid (violations or none), running (run id,
  started), last_run, last_success, last_failure -- each of the last
  three a summary: run_id, status, started, ended, reason, usage
- usage per scope (`global`, each backend, each chore with a ceiling):
  rolling-24h usage and the ceiling, so remaining is ceiling minus usage,
  per dimension (tokens, usd, turns); subscription-billed usage counts
  toward tokens and turns, not usd
- scheduler: last_tick, stale (last tick older than 3 intervals),
  installed (true / false / unknown), tick interval, ledger row count
- notifications (unread and read)
- warnings and problems: free-text lines, e.g. "ledger shrank from 4210
  rows to 3900 since the last tick", "installed tick interval 120s
  differs from config 60s; run `chores install` again", a state directory
  that could not be read

Beyond the snapshot, surfaces can query: past runs filtered by chore,
time window and status set (newest first); one run's record and any of
its five artifacts; the state directory's size on disk.

## 4. Actions the system supports

| Action | Effect | Rules |
|---|---|---|
| run now | start one run of a chore outside its schedule | subject to admission; `force` overrides overlap, battery and offline only -- never global pause, breaker pause, or ceilings |
| dry run | show the resolved plan (backend, model, cwd, env names, secret names, budget, applicable ceilings, admission verdict) and execute nothing | always allowed |
| pause (global) | nothing starts by any path until resume; takes a reason | the kill switch |
| pause (chore) | this chore stops being admitted | takes a reason |
| resume | clears the global pause, or one chore's pause (operator or breaker) | |
| kill | signal a running run's process group | the run ends KILLED |
| dismiss | mark a notification read | |
| prune | delete run directories older than the retention window | the ledger and notifications are never pruned |
| validate | check every definition; list every violation | |
| install / uninstall | put the 60-second tick into the OS scheduler, or remove it | |

Not supported, by design: editing, enabling, disabling, creating, copying
or deleting a definition (git does that); running a chore that is invalid.

## 5. Conditions that may need the operator

- the scheduler is not installed, or is stale (no tick for 3+ intervals)
- global pause is on
- a chore was paused by the circuit breaker
- a definition is invalid
- a chore's last run ended FAILED, TIMED_OUT, BUDGET_EXCEEDED, OFFLINE,
  INTERRUPTED or KILLED
- slots were MISSED, SKIPPED_* or DEFERRED_BATTERY
- a ceiling is near or at exhaustion (any scope, any dimension)
- a run is still RUNNING well past what is normal for it
- unread notifications, alert or info
- a warning or problem line (ledger shrank, tick interval mismatch,
  unreadable state)
- a run record is truncated

---

# Constraints and non-goals

- **Terminal-first.** There is no windowed GUI. Anything that needs a
  window is a terminal program; the Dock tile opens a terminal running
  the dashboard. The dashboard is a Python full-screen terminal app
  (Textual-class toolkit: widgets, tables, scrolling panes, modal
  dialogs, mouse support, truecolor where available).
- **Must work at 80x24**, over ssh, in macOS Terminal, iTerm2 and a Linux
  terminal. Menu bar and Dock are macOS-only; the dashboard and CLI are
  cross-platform.
- **Read-only over definitions.** Actions are the list in Domain
  reference 4, nothing more.
- **One user, one machine.** No accounts, no sharing, no remote view.
- **No filesystem diffing.** "What did a run change on disk" is not
  knowable in v1 (no sandbox).
- **No in-run judgement.** Nothing evaluates a run's content while it is
  happening; bounds are budget, timeout and the cross-run breaker.
- **No metrics backend.** Usage is the 24h rolling window from the
  ledger; there is no long-term chart store. Trend views must be
  computable from run records.
- **Polling, not push.** Surfaces refresh on an interval; data can be
  stale and must say so.
- **Secrets never appear.** Values are redacted everywhere; secret names
  may be shown.

---

# Sample snapshot

Use this in every wireframe. Local time; snapshot taken Sat 2026-09-26
14:05:12.

Scheduler: installed, tick 60s, last tick 14:04:31 (not stale), 4210
ledger rows. Global pause: none. Warnings: none.

Rolling-24h usage:

| Scope | tokens | usd | turns |
|---|---|---|---|
| global | 182,400 / 500,000 | 1.84 / -- | 41 / 200 |
| backend `local` (local model, metered, unpriced) | 96,100 / -- | -- | -- |
| backend `gateway` (cloud, metered, priced) | 40,300 / 100,000 | 1.84 / 3.00 | -- |
| backend `agent-cli` (subscription) | 46,000 / -- | -- | 41 / 150 |
| chore `pr-digest` | 52,300 / 60,000 | -- | 18 / 20 |

Chores:

| name | kind / backend | schedule | state | last run | last success | next due |
|---|---|---|---|---|---|---|
| daily-local-smoke | prompt / local | `0 4 * * *` | enabled | SUCCEEDED 04:00:03, 1.9s, 212 tok | same | Sun 04:00 |
| weekly-gateway-smoke | prompt / gateway | `0 9 * * 1` | enabled | OFFLINE Mon 09:00:04, "backend gateway unreachable" | Mon 2026-09-14 09:00 | Mon 09:00 |
| log-brand-sweep | command | `*/30 * * * *` | enabled; RUNNING since 14:00:02 | SUCCEEDED 13:30:01, 41s | 13:30:01 | 14:30 |
| inbox-triage | agent / agent-cli | `0 * * * *` | PAUSED by breaker: "3 consecutive failures" | TIMED_OUT 12:00:00, 600s, 7 turns | 08:00:00 | -- |
| pr-digest | agent / agent-cli | `45 8 * * *` | enabled | BUDGET_EXCEEDED 08:45:00, "tokens 52,300 > budget 50,000" | Fri 08:45 | Sun 08:45 |
| workspace-gc | command | `0 3 * * *` | enabled | MISSED x2 (asleep 01:10-07:55), catch_up off | Thu 03:00 | Sun 03:00 |
| notes-summarize | prompt / gateway | `15 */2 * * *` | INVALID: "budget lacks usd; backend gateway has a usd ceiling" | INVALID 14:04:31 | Wed 18:15 | -- |
| release-notes-draft | prompt / gateway | `0 13 * * 1-5` | enabled | SKIPPED_CEILING 13:00:01, "usd 1.84 + 1.50 would cross gateway ceiling 3.00" | Thu 13:00 | Mon 13:00 |
| repo-cleanup | command | `0 5 * * 0` | DISABLED (in git) | SUCCEEDED 2026-08-30 05:00 | same | -- |

Notifications (newest first):

| id | at | level | chore | text | read |
|---|---|---|---|---|---|
| n-0412 | 12:00:01 | alert | inbox-triage | paused by breaker after 3 consecutive failures (TIMED_OUT, TIMED_OUT, FAILED) | no |
| n-0409 | 08:52:10 | alert | pr-digest | BUDGET_EXCEEDED: tokens 52,300 > budget 50,000 | no |
| n-0408 | 08:51:57 | info | pr-digest | 3 PRs need your review (posted by the chore) | no |
| n-0391 | Mon 09:00 | info | weekly-gateway-smoke | OFFLINE: backend gateway unreachable | yes |

One run record for the run view: `pr-digest-20260926T154500Z-k3f9`,
agent, backend agent-cli, model (backend default), billing subscription,
started 08:45:00, ended 08:52:09, status BUDGET_EXCEEDED, reason "tokens
52,300 > budget 50,000", usage tokens_in 44,100 / tokens_out 8,200 /
turns 18 / 429 s wall / 12.4 s cpu / 1.8 MB disk, exit code 0,
definition_rev `a41c9e2-dirty`, not truncated. Transcript 1,240 JSON
lines; stdout 3 lines; stderr empty; errors 1 line. The previous
successful run's snapshot differs by one line: `budget: {tokens: 60000}`
became `budget: {tokens: 50000}`.

Alternate states to show in the state catalogue: global pause "on a
flight" set at 06:40; scheduler stale since 09:12 (laptop woke at 13:58,
agent unloaded); not installed; ledger shrank 4210 -> 3900; zero chores.

---

# User stories

These are the operator's intent, unedited. Some are out of v1 by the
constraints above; say so in the traceability table rather than dropping
them.

## Stories: defining

Writing a task down and keeping it in git.

- As a task author, I can write a task's definition -- what it runs, when,
  with which permissions, in which sandbox, against which LLM backends --
  in one place I can read back later.
- As a task author, I can commit that definition to git and see every
  past version of it.
- As a task author, I can diff a task's definition between two runs and
  see what changed.
- As a task author, I can disable a task without deleting it.
- As a task author, I can dry-run a task and see what it would do without
  it doing it.
- As a task author, I can name which LLM backends a task may use -- a
  cloud model, a subscription, a local model -- and which it may not.
- As a task author, I can write a task that touches no LLM at all and
  have it live alongside the ones that do.
- As a task author, I can copy an existing task as the starting point for
  a new one.
- As a task author, I can see, before enabling a task, what it will be
  allowed to spend and how long it will be allowed to run.

## Stories: running

A run firing, and what bounds it.

- As an operator, I can rely on a task firing on its schedule while the
  laptop is awake.
- As an operator, I can see that a run was missed because the laptop was
  asleep or off, rather than have it silently skipped.
- As a task, I run inside the sandbox my definition names and cannot reach
  outside it.
- As a task, I can use only the credentials my definition grants me.
- As a task, I stop when I hit my budget, and I stop when I hit my
  timeout, whichever comes first.
- As a task, I do not start a second run while my previous run is still
  going.
- As an operator, I can trigger a run by hand, outside its schedule.
- As an operator, I can stop a running task.
- As the LLM inside a task, I can find out how much budget I have left.
- As a task, I can post a short message that the operator will see on the
  dashboard.

## Stories: guarding

Not running amok.

- As an operator, I can be certain that a badly configured task cannot
  exhaust my spend, my tokens, my disk, or my cpu.
- As an operator, I can set a ceiling per task and a ceiling across all
  tasks, and the smaller one wins.
- As an operator, I can set a ceiling per backend, so one subscription or
  one model cannot be drained by the herd.
- As an operator, I can hit one kill switch that stops every task and
  prevents any from starting.
- As an operator, I can see that a run was stopped for misbehaving and
  why.
- As a reviewer, I can be sure no credential ever appears in a
  transcript, a log, or a console capture.
- As a task, I cannot escalate my own permissions or budget.
- As an operator, I can be told, loudly, when a task has failed several
  times in a row.
- As an operator, I can see what a task did to my filesystem.

## Stories: watching

The dashboard, from Dock, menu bar, or terminal.

- As an operator, I can see every scheduled task, whether it is running
  now, its last status, and its next run, on one screen.
- As an operator, I can see usage -- cpu, disk, tokens, spend -- per task
  and in total.
- As an operator, I can see the last known success and the last known
  error for each task.
- As an operator, I can see a message a task posted, and dismiss it.
- As an operator, I can open the dashboard from the Dock.
- As an operator, I can open the dashboard from a terminal and see the
  same information as a TUI.
- As an operator, I can glance at a menu-bar item and know whether
  anything needs me without opening anything.
- As an operator, I can get from the dashboard to a run's transcript in
  one step.
- As an operator, I can tell at a glance which tasks are disabled.

## Stories: reviewing

Looking back at runs, by hand and by program.

- As a reviewer, I can see every past run of a task, with when it ran,
  how it ended, and what it cost.
- As a reviewer, I can read a run's transcript, its errors, and its
  console output as three separate things.
- As a reviewer, I can pull the transcripts and outputs for one run, for
  a set of runs, or for a date range, from a script.
- As a reviewer, I can compare a run against the exact definition that
  produced it.
- As a reviewer, I can find the last successful run and the last failed
  run of any task without scrolling.
- As a reviewer, I can ask which runs over the last month blew their
  budget, timed out, or errored, and get a list.
- As a reviewer, I can feed a set of runs to an LLM to look for patterns
  I would not spot by eye.
- As a reviewer, I can tell from a run's record which backend and model
  actually served it.

## Stories: degrading

Offline, on battery, and other laptop realities.

- As an operator on a flight, I can see that cloud-backed tasks failed
  fast because there was no network, not because anything was wrong with
  them.
- As a task that only needs a local model, I keep running when the
  network is gone.
- As an operator on battery, I can have heavy tasks defer until I am
  plugged in.
- As an operator, I can tell the dashboard is showing me stale
  information rather than have stale read as fresh.
- As an operator, I can close the lid mid-run and get a run record that
  says the run was interrupted, not one that lies.
- As an operator, I can come back online and have missed runs reported
  to me rather than all fired at once.

