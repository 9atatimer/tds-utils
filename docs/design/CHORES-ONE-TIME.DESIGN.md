# chores: one-time chores and armed runs

> **Status:** APPROVED (2026-10-03, Todd Stumpf: "landed. lets get this to POC/MVP asafp"; open questions taken as proposed -- Q1 no relative times, Q2 abandon on disable, Q3 K3 in the default run)
> **Date:** 2026-10-03
> **Authors:** Todd Stumpf (intent, `docs/concepts/one-time-chores/`), Claude (design)
> **Amends:** [CHORES.DESIGN.md](./CHORES.DESIGN.md) (APPROVED; frozen) -- Subsystems 1, 2, 3 and 6, the Run state machine and the Data Model, as listed under "What this amends". Nothing here edits that record; on approval it gains one appended Key Decisions row pointing here.
> **Origin:** issue #399; concept PR #395

---

## Overview

A chore no longer has to recur. A **manual** chore has no schedule and runs
only when someone asks. Any chore -- manual or scheduled -- can be asked to
run **now** or **armed** to run at a start time the asker gives, and the
tick fires an armed run when its time comes. The LMDE/CLAI smoketest uses
this to kick the tires: it runs the machine's `smoketest-*` manual chores
now, arms one, and grades both, in minutes rather than a wait for cron.

---

## Goals

- **G1 Manual chores exist.** A definition with `schedule: manual` is
  valid, is never fired by the tick, never produces a MISSED record, and
  shows `manual` in the schedule column on every status surface.
- **G2 Run now, as today.** `chores run <name>` runs any chore, manual or
  scheduled, immediately, through the same admission as every run.
  Unchanged from CHORES.DESIGN.md Subsystem 3.
- **G3 Arm for later.** `chores run <name> --at <time>` writes an ARMED
  record and returns at once. The first tick at or after that time starts
  the run through normal admission. Status shows the armed time as the
  chore's `next`.
- **G4 An armed run is never lost silently.** If the laptop sleeps past the
  start time, the first tick after waking starts the run and its record
  states how late it started. An armed run that never starts (cancelled,
  refused at admission, or its chore deleted or made invalid) ends in a
  terminal status with a reason; none stays ARMED forever.
- **G5 Same guard rails.** A run started from an arming is admitted exactly
  like any other: global PAUSED, breaker pause, overlap, battery deferral,
  offline and every ceiling apply. Arming is not an override; `--at` and
  `--force` cannot be combined.
- **G6 The smoketest kicks the tires.** On a laptop with the herd installed,
  `test/smoketest_lmde_clai/run-probes.sh` runs every `smoketest-*` manual
  chore now and asserts each SUCCEEDED, arms one at the current minute and
  asserts the tick started it within two tick intervals, and asserts the
  scheduler is installed and not stale. In the cloud column every chores
  probe is SKIP (no herd there).

---

## Non-Goals

- **A start time inside the definition.** "When" is the asker's, given at
  ask time; the definition stays timeless. A chore that should run at a
  fixed time every day is a cron chore.
- **Run-exactly-once-ever semantics.** A manual chore runs once per ask, as
  many times as it is asked. Nothing records that a chore "has run" and
  refuses a second ask.
- **A queue.** One armed run per chore at a time. Arming a chore that is
  already armed replaces nothing and is refused with the existing run id.
- **Recurring arming** ("every Tuesday") -- that is `schedule`.
- **Built-in smoketest chores shipped by tds-utils.** Definitions live in
  the operator's private `$CHORES_HOME` (CHORES.DESIGN.md Subsystem 1); the
  smoketest finds `smoketest-*` there and never writes one.
- **Arming from the menu bar.** The TUI and CLI arm; the menu bar keeps its
  current verbs.

---

## Architecture Overview

```
  chores run <name> [--at T]          tick (every interval)
         |                                  |
         | now: run_chore (unchanged)       | for each chore:
         | --at: arm_chore -> ARMED record  |   cron chore: due_policy (unchanged)
         v                                  |   manual chore: never due
  +------------------------------+          |   ARMED record at/after T:
  | application                  |<---------+     armed_policy -> FIRE_ARMED
  |  arm_chore, cancel_armed,    |          |     admission_policy (unchanged)
  |  tick._consider + armed pass |          |     spawn run_chore(..., run_id)
  +--------------+---------------+          v
                 | ports (unchanged)    one run directory: ARMED -> PENDING
                 v                      -> RUNNING -> terminal, one run_id
  +------------------------------+
  | domain                       |
  |  Schedule | Manual (trigger) |
  |  armed_policy (new, pure)    |
  |  RunStatus += ARMED,         |
  |   CANCELLED, ARM_ABANDONED   |
  +------------------------------+

  smoketest_lmde_clai/probe-chores.sh (laptop column only):
    K1 scheduler installed, not stale   -> chores status --json
    K2 every smoketest-* manual chore   -> chores run <c>; record SUCCEEDED
    K3 arm smoketest-* at now           -> chores run <c> --at now;
                                           SUCCEEDED within 2 tick intervals
```

No new port, adapter or dependency. An arming is a run record in the
existing store, so history, status and the dashboard need no second store.

---

## Design

### Subsystem 1 (amended): Definitions

| Change | Details |
|---|---|
| `schedule` accepts `manual` | The value is a 5-field cron expression or the literal `manual`. Parsing yields a `Trigger`: `Cron(Schedule)` or `Manual`. Every other field is unchanged |
| `catch_up` with `manual` | INVALID: there are no slots to catch up |
| Validation | A missing `schedule` stays INVALID ("schedule is required"); "never scheduled" must be written down, not defaulted |

### Subsystem 2 (amended): Scheduler (tick)

| Responsibility | Change |
|---|---|
| Due detection | A `Manual` chore is never due: no window, no slots, no MISSED records, no first-sight bookkeeping |
| Armed pass | After the existing per-chore pass, for each ARMED record: domain `armed_policy(start_at, now)` returns FIRE_ARMED once `now >= start_at`, else WAIT. On FIRE_ARMED, the tick runs `admission_policy` (unchanged) and on ADMIT spawns `chores run <name> --armed <run-id>` detached, as Subsystem 2's Spawn row does today |
| Refused at fire time | An admission refusal ends the arming: the record goes to the refusal's terminal status (SKIPPED_PAUSED, SKIPPED_CEILING, ...) with the reason. An ask is consumed by its first fire attempt, like a cron slot; the operator asks again. The one exception mirrors `defer_on_battery`: a battery refusal leaves the record ARMED, and it fires on the first tick with AC power |
| Abandoned | An ARMED record whose chore no longer exists, or is now INVALID or `enabled: false`, goes to ARM_ABANDONED with that reason at the next tick |
| Lateness | When a fire happens more than `missed_grace_sec` after `start_at` (the laptop slept), the record carries `late_sec`. A one-time ask is intent to run once, not a slot, so lateness never turns it into MISSED |

### Subsystem 3 (amended): Runner (run)

| Responsibility | Change |
|---|---|
| `--at <time>` | `arm_chore`: validates the chore (it must exist and be valid), refuses when the chore already has an ARMED record (reason names its run id), and writes an ARMED record (run id, chore, `start_at`, `armed_at`, `armed_by: cli or tui`). It starts nothing and returns the run id. `<time>` is `now`, `HH:MM` (the next occurrence, local), or ISO 8601 local date-time; a time in the past is refused unless it is `now` |
| `--armed <run-id>` | Used only by the tick. The runner adopts the ARMED record's run id and directory instead of minting a new one, re-runs admission with live state (as today), and proceeds; one run, one directory, one ledger row |
| `--at` with `--force` or `--dry-run` | Refused: arming is not an override, and a dry run of a future run is the plain `--dry-run` |
| `chores cancel <run-id>` | `cancel_armed`: an ARMED record becomes CANCELLED. Any other status is refused (`chores kill` is the verb for a running run) |

### Subsystem 6 (amended): Status surfaces

| Change | Details |
|---|---|
| Schedule column | `manual` for a Manual chore |
| `next` column | the earliest of the cron next-due (unchanged) and an ARMED record's `start_at`, marked `armed`. A manual chore with nothing armed shows `-` |
| TUI | a verb to arm the selected chore at a time, and one to cancel its armed run |
| `--json` | `ChoreStatus` gains `armed: {run_id, start_at} or null` |

### The smoketest probe (tds-utils `test/smoketest_lmde_clai/`)

A fourth probe file, `probe-chores.sh`, added to `run-probes.sh`'s list.
Laptop column assert, cloud column skip (`CLAUDE_CODE_REMOTE=true`), the
same convention as C2.

| id | check | laptop | cloud |
|----|-------|--------|-------|
| K1 | `chores status --json`: scheduler installed and not stale | assert | skip |
| K2 | every `smoketest-*` chore with `schedule: manual`: `chores run <c>` exits with the record SUCCEEDED | assert | skip |
| K3 | arm the first such chore with `--at now`; within two tick intervals its record is SUCCEEDED and `started` is at or after `start_at` | assert | skip |

- **No `smoketest-*` manual chore defined:** K2 and K3 FAIL with a message
  naming the missing definitions. A laptop with the herd installed and no
  smoketest chores is misconfigured, not exempt.
- **Herd not installed** (`chores` absent or scheduler not installed): K1
  FAILs, and K2 and K3 SKIP with K1's reason.
- **Spend:** the probe never chooses what a smoketest chore does; the
  operator's definitions do, under their own budgets and ceilings. The
  first-cut definitions (operator's repo, not this one) are a `command`
  chore (`/bin/echo`, no spend) and a `prompt` chore on the local Ollama
  backend with a small token budget.
- **Duration:** K3 waits at most two tick intervals (two minutes at the
  default) and polls `chores runs --json` within that bound. This is the
  only wait in the suite, and it is bounded.

---

## Behaviors and Interfaces

| Behavior | Use case (signature) | Ports it needs | Given / When / Then |
|---|---|---|---|
| A manual chore is valid and never fires | `tick(deps: TickDeps) -> TickReport` (unchanged signature) | store, clock | Given a definition with `schedule: manual`, When ticks pass across any span, Then no run, MISSED or first-sight record is written for it |
| `manual` with `catch_up` is rejected | `load_context(...)` via definitions parsing (unchanged signature) | definitions | Given `schedule: manual` and `catch_up: true`, When definitions load, Then the chore is INVALID with a reason naming `catch_up` |
| A chore is armed | `arm_chore(name: str, start_at: datetime, deps: RunDeps, *, armed_by: str) -> ArmOutcome` | store, clock | Given a valid chore with nothing armed, When it is armed for 15:30, Then an ARMED record exists with `start_at` 15:30 and no process started |
| A second arming is refused | `arm_chore` (same) | store | Given a chore already ARMED as run R, When it is armed again, Then the outcome is refused, naming R, and R is unchanged |
| A past start time is refused | `arm_chore` (same) | clock | Given now is 15:30, When armed for 15:00 (not `now`), Then refused; no record |
| The tick fires an armed run at its time | `tick` (unchanged) | store, clock, process | Given run R ARMED for 15:30, When a tick runs at 15:30:20, Then `chores run --armed R` is spawned and R becomes PENDING |
| An armed run waits | `tick` (unchanged) | store, clock | Given R ARMED for 15:30, When a tick runs at 15:29, Then R stays ARMED and nothing is spawned |
| A late fire is recorded, not missed | `tick` (unchanged) | store, clock | Given R ARMED for 15:30 and no tick until 18:00, When the 18:00 tick runs, Then R is started and its record carries `late_sec` = 9000 |
| Admission refusal consumes the ask | `tick` (unchanged) | store, clock | Given R ARMED and the global PAUSED sentry present, When R's time comes, Then R ends SKIPPED_PAUSED with the reason and is not retried |
| Battery keeps the arming | `tick` (unchanged) | store, clock, power | Given R ARMED for a `defer_on_battery` chore on battery, When its time comes, Then R stays ARMED; on the first AC tick it fires |
| An orphaned arming is abandoned | `tick` (unchanged) | store, definitions | Given R ARMED and its chore deleted, When the next tick runs, Then R ends ARM_ABANDONED naming the reason |
| The runner adopts the armed id | `run_chore(name: str, deps: RunDeps, *, force: bool = False, dry_run: bool = False, armed_run_id: str or None = None) -> RunOutcome` | store, process, backends | Given R ARMED and admitted, When `run_chore(..., armed_run_id=R)` runs, Then the run's id and directory are R's and exactly one ledger row is written |
| An armed run is cancelled | `cancel_armed(run_id: str, deps: Deps) -> bool` | store | Given R ARMED, When cancelled, Then R is CANCELLED and the tick never fires it; Given R RUNNING, Then refused |
| Status shows the arming | `status(deps: Deps) -> StatusView` (unchanged signature) | store, clock | Given a manual chore armed for 15:30, When status renders, Then schedule is `manual` and next is `15:30 armed` |

`ArmOutcome`: `run_id or None`, `message`. `Trigger`, `armed_policy` and
the new statuses are domain values; `arm_chore` and `cancel_armed` are
application use cases beside `run_chore`; the CLI and TUI are thin entry
points over them.

---

## State Machine

### Run (amended)

New non-terminal status ARMED before PENDING; new terminal statuses
CANCELLED and ARM_ABANDONED. Everything from PENDING on is unchanged.

```
   chores run --at T
   ------------------> +-------+  tick: now >= T, ADMIT   +---------+
                       | ARMED |------------------------->| PENDING |--> (unchanged)
                       +---+---+                          +---------+
                           |  tick: refusal (not battery) -> SKIPPED_* (terminal)
                           |  chores cancel               -> CANCELLED (terminal)
                           |  tick: chore gone/invalid/
                           |        disabled              -> ARM_ABANDONED (terminal)
                           +--  tick: battery refusal     -> stays ARMED
```

| From | To | Trigger | Condition |
|---|---|---|---|
| (none) | ARMED | `chores run <name> --at T` | chore valid, nothing armed, T is `now` or not past |
| ARMED | ARMED | tick | `now < T`, or battery refusal of a `defer_on_battery` chore |
| ARMED | PENDING | tick | `now >= T` and admission ADMIT; `late_sec` set when `now - T > missed_grace_sec` |
| ARMED | SKIPPED_PAUSED / SKIPPED_CEILING / SKIPPED_OVERLAP / SKIPPED_OFFLINE | tick | `now >= T` and admission refuses for that reason |
| ARMED | CANCELLED | `chores cancel <run-id>` | -- |
| ARMED | ARM_ABANDONED | tick | the chore no longer exists, is INVALID, or is `enabled: false` |

ARMED records are excluded from the in-flight reservation (CHORES.DESIGN.md
Key Decisions, issue #283): an arming holds no budget until it is admitted.

---

## Data Model

Definition (`chores/<name>.md`), amended field:

```
schedule        5-field cron, local time | "manual"
```

Run record (`run.json`), added fields (absent on records that were never
armed):

```
start_at        ISO 8601 UTC; when the asker wanted it
armed_at        ISO 8601 UTC; when it was armed
armed_by        "cli" | "tui"
late_sec        int; set when the fire came more than missed_grace_sec after start_at
```

`status` gains ARMED (non-terminal), CANCELLED and ARM_ABANDONED
(terminal). CANCELLED and ARM_ABANDONED write a ledger row like any
terminal status, with zero usage, so history is complete.

---

## Security Considerations

- **Arming is not an override.** G5: every guard rail applies at fire time
  with live state. `--at --force` is refused, so a run cannot be scheduled
  past PAUSED or a ceiling.
- **An armed run executes the definition as it is at fire time,** not as it
  was when armed: the runner snapshots `definition.md` when it starts, as
  today. An arming made against a harmless definition runs whatever the
  definition says by then. That matches "definitions are trusted input"
  (CHORES.DESIGN.md), and the snapshot makes the change visible.
- **The smoketest spends only what the operator defined.** The probe picks
  chores by name and kind, never their content; a `smoketest-*` chore that
  spends money is the operator's choice, bounded by its budget and the
  ceilings.
- **No new input surface.** `--at` is parsed by the CLI into a domain
  `datetime`; nothing from it reaches a shell, a prompt or a path.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the start time lives | given at ask time (`--at`), never in the definition | Todd's concept: "only run manually ... can be given a start time, or start immediately"; the asker owns when, the definition owns what |
| How "never scheduled" is written | `schedule: manual`, an explicit literal | a missing schedule staying INVALID keeps a typo from silently becoming a chore that never runs |
| An arming is a run record | status ARMED in the existing run store, one run id from arming to terminal | history, status and the dashboard work unchanged; no second store to reconcile |
| Who fires an armed run | the existing tick, with a pure `armed_policy` | the scheduler already owns time, sleep and admission; no timer per arming |
| Once per ask | a manual chore runs each time it is asked | "one-time" describes the ask, not the chore; once-ever needs a record no one asked for |
| Refusal at fire time | consumes the ask (terminal SKIPPED_*), except battery, which keeps it ARMED | mirrors cron slots and `defer_on_battery`; an ask silently retried later would fire at a time nobody chose |
| Late fire | runs late with `late_sec`, never MISSED | an ask is intent to run once; MISSED exists so a herd of slots is not replayed after sleep, which cannot happen with one arming per chore |
| One arming per chore | a second `--at` is refused | no queue to design; the operator cancels and re-arms |
| Armed runs hold no budget | excluded from the issue #283 in-flight reservation until admitted | an arming for tomorrow must not shrink today's headroom |
| Smoketest chores | the operator's `smoketest-*` manual chores in `$CHORES_HOME`, found by name | definitions are private (CHORES.DESIGN.md Subsystem 1); the public suite must not ship or write one |
| Smoketest placement | `test/smoketest_lmde_clai/probe-chores.sh`, laptop assert, cloud skip | Todd, 2026-10-03: "THE smoketest"; the cloud has no herd, as C2 is skipped there |
| Missing smoketest chores | FAIL, not SKIP, when the herd is installed | an installed herd with nothing to kick the tires with is the misconfiguration the probe exists to catch |

---

## Open Questions

- **Q1 `--at` forms.** `now`, `HH:MM` (next occurrence, local) and ISO 8601
  local date-time are proposed. Is relative time (`+5m`) wanted?
- **Q2 Abandon on disable.** An arming whose chore is set
  `enabled: false` before its time is proposed to end ARM_ABANDONED. The
  alternative is to keep it ARMED until re-enabled. Todd's call.
- **Q3 K3's cost.** K3 makes the smoketest wait up to two tick intervals.
  Keep it in the default run, or behind a flag for a quick pass?

---

## Rejections

- **A `start_at` field in the definition** -- puts "when" in a git-tracked
  file for a one-off, and a stale value would fire unexpectedly after the
  next edit.
- **A separate arming store (`armed.d/`)** -- a second place to reconcile
  with the run store, and its records would need their own history and
  status rendering.
- **`at(1)` / launchd one-shot jobs per arming** -- install state per run,
  outside admission, invisible to the dashboard: the Rejections of
  CHORES.DESIGN.md (crontab, one plist per chore) apply.
- **Treating lateness past grace as MISSED** -- would drop the one run the
  operator explicitly asked for because the lid was closed.
- **Shipping smoketest chore definitions in tds-utils** -- public repo,
  private herd; the definitions name the operator's backends.
- **`--at` overriding PAUSED or ceilings** -- the kill switch has to hold on
  every path (CHORES.DESIGN.md Key Decisions, "Admission location").

---

## Future Considerations

- **Arming from the menu bar.**
- **A queue of armings per chore**, if one ever proves necessary.
- **Webhook-triggered runs** (concept `chores-webhooks`) would reuse the
  armed-run path: a delivery becomes an arming at `now` carrying its
  payload.

---

## What this amends

Each frozen section of CHORES.DESIGN.md this record changes, for the
reviewer and for the retrospective's drift walk:

| CHORES.DESIGN.md section | Amended by |
|---|---|
| Subsystem 1, front-matter `schedule` | Subsystem 1 (amended) above |
| Subsystem 2, Due detection and Missed detection | Subsystem 2 (amended): manual chores are never due; the armed pass |
| Subsystem 3, `chores run` | Subsystem 3 (amended): `--at`, `--armed`, `chores cancel` |
| Subsystem 6, `StatusView` | Subsystem 6 (amended) |
| State Machine, Run | State Machine above: ARMED, CANCELLED, ARM_ABANDONED |
| Data Model, front-matter and run record | Data Model above |
| Goals, "Missed is recorded, not replayed" | unchanged for cron slots; G4 states the armed rule |

---

## Related Documents

- [CHORES.DESIGN.md](./CHORES.DESIGN.md) -- the record this amends
  (APPROVED, frozen)
- `docs/concepts/one-time-chores/` -- the concept (non-binding)
- `test/smoketest_lmde_clai/README.md` -- the suite the probe joins
- `docs/concepts/chores-webhooks/` -- the next trigger kind, which would
  reuse the armed-run path
