# LMDE Tasks

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-09-13  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

We are going to be adding a new set of tools to the LMDE ecosystem --
Tasks.

The Task system is both a set of approaches and skills for crontab jobs,
and also porcelain for crontab. If there is a well-known TUI/GUI for
crontab that is extensible, we can use that as a foundation, but I suspect
it will be straightforward enough to just roll our own. And fun.

I want to be able to manage a herd of small LLM-involved tasks that are
invoked periodically by a job manager (i.e. cron). Those tasks will involve
LLMs -- and their credentials, and their budget constraints, and their
timeouts. It is completely legit to have a task that does not touch an LLM,
e.g. clean up their workspace, but if it is in the Task system its mental
model is going to be LLM-adjacent.

We need to be mindful of being retrospective on these tasks: tracking
errors and output for later analysis and improvement. We need to be
watchful of these tasks, as LLMs are prone to misbehave.

It needs to provide high QoL expectations with these Tasks. The UI has to
be low-friction, easy to understand, easy to use. The dashboard should be
easily accessible by Dock or Dashboard or CLI.

It needs to be safe and secure. We need to be certain that we do not run
amok and burn all our resources on a poorly configured job (or a badly
behaving query).

A Task needs:

- a durable definition of the task, its schedule, its permissions, its
  sandbox
- a history of past runs, with logs, errors and transcripts distinct from
  console output
- a way to programmatically access the logs/transcripts/output for a run
  or a set of runs
- a history of its definition in git
- the enabled LLM backends (model / subscriptions / local / cloud)

The Task dashboard needs:

- the scheduled Tasks, whether they are running, last status, next run
- usage consumption (cpu / disk / tokens / spend)
- maybe a way for a task to post a message, a notification that shows up
  in the dashboard
- last status, last known success / error
- to work as GUI or TUI
- a concept of network disconnect and graceful failure, for flights or
  out of battery

Out of scope for v1: cloud tasks. Everything is laptop-local for now.

## Story sets

| File | Theme |
|---|---|
| STORIES.defining.md | writing a task down and keeping it in git |
| STORIES.running.md | a run firing, and what bounds it |
| STORIES.reviewing.md | looking back at runs, by hand and by program |
| STORIES.watching.md | the dashboard, from Dock, menu bar, or terminal |
| STORIES.guarding.md | not running amok |
| STORIES.degrading.md | offline, on battery, and other laptop realities |

## Notes

**Settled in session (Todd's words):**

- Cloud tasks are out of scope for v1. Everything is laptop-local.
- A task that never touches an LLM is a legitimate member; the mental
  model stays LLM-adjacent regardless.
- The definition's history lives in git.
- Logs, errors and transcripts are kept distinct from console output.
- The dashboard works as GUI and as TUI, and is reachable from the Dock,
  a dashboard surface, or the CLI.
- Network loss and battery exhaustion are expected conditions, not
  failures to be surprised by.

**Still open (nobody's yet):**

- The name. "Tasks" collides with the todo-plan skill's `tasks/` work-item
  directory and with `gadmin task` (template-tools
  `docs/design/DESIGN.GADMIN-TASK.md`). This directory is `lmde-tasks` as
  a working label only.
- Crontab porcelain over an existing extensible crontab TUI, or roll our
  own. Recorded as Todd said it: use one if it exists, otherwise roll our
  own. Fact for the next phase: nothing in tds-utils or template-tools
  uses cron or a `StartCalendarInterval` plist today; the laptop precedent
  is launchd keep-alive daemons that poll on a timer.
- What a budget is denominated in. Tokens, dollars, wall-clock, turns, or
  all of them. Two fleet precedents already disagree: designomatic budgets
  in USD (soft / hard limits), ci.magic budgets in agent turns, and a
  subscription-billed headless `claude -p` call has no per-call cost at
  all.
- What "sandbox" means on a laptop.
- Whether the cloud Claude Code Routines (tds-internal
  `ops/claude-code/routines/`) and local Tasks are one definition shape
  with two runners, or two things. Both readings were on the table.
- Where usage numbers (cpu / disk / tokens / spend) come from, per
  backend.

**Aspirational, may not be buildable as stated:**

- A misbehaving LLM run is detected and stopped automatically, not just
  bounded by a budget.
- Spend is known per run for every backend, including subscription-billed
  ones.

**What the idea leans on that exists (placement only, nothing chosen):**

- Claude Code Routines, the cloud sibling: YAML front-matter plus a
  verbatim prompt body, git as truth, a sha drift check
  (tds-internal `ops/claude-code/routines/`, `scripts/routines/`).
- `tmux_shepherd.sh` in cron mode handing archived logs to `log_brander`
  for an LLM slug -- an LLM cron job that exists today with no history,
  budget, or dashboard.
- `goldfish --llm`, which calls `claude -p` or `ollama run` from a script.
- The launchd / systemd daemon twins (`macos/launchd/`, `local/systemd/`)
  and the rumps menu-bar apps (`bin/lmde-sync-monitor`,
  `bin/skills-drift-monitor`); `macos/apps/mkmacapp` for Dock tiles.
- The agent-notifications design (NATS KV with a filesystem fallback),
  `docs/design/AGENT-NOTIFICATIONS.DESIGN.md`, DRAFT.
- The observability stack, which already derives `gen_ai` token metrics
  into Grafana (`lmde/components/observability/`).
- designomatic's spend-limit policy and metered LLM port, and ci.magic's
  headless `claude -p` adapter (template-tools).
- The data-warehouse ledgers: append-only NDJSON per producing system
  (template-tools `docs/design/ARCHITECTURE.DATA-WAREHOUSE.md`).
- The orchestrator design, DRAFT since April, the big sibling of this
  small cron-shaped idea (`docs/design/ORCHESTRATOR.DESIGN.md`).
- 1Password `op` as the only sanctioned credential source (`lmde/LMDE.md`).

**What the idea leans on that does not exist yet:**

- Per-run token and spend accounting for every backend.
- A laptop sandbox story for a task.
- A notification sink the dashboard reads.
- Any TUI or GUI framework, scheduler, or local database on the tech
  radar (`lmde/TECH_RADAR.md`).
