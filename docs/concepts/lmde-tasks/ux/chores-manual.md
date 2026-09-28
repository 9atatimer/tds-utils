# chores -- User and Implementation Manual

Version 1, 2026-09-27. Companion to:

- `Chores App.dc.html` -- the Mac app (primary surface)
- `Chores Prototype.dc.html` -- the terminal dashboard (TUI), with the menu-bar item and Dock tile around it
- `chores-ux-design.md` -- the TUI wireframes, CLI output and the story traceability table

Each section has two parts:

- **Use** -- what the operator sees and does.
- **Wire** -- where each piece of data comes from, which action each control calls, what refreshes it, and the rules the implementation must keep.

---

## 0. Conventions

| Notation | Meaning |
|---|---|
| `S.x` | field `x` of the **status snapshot** (Domain reference 3) |
| `S.chore[n].x` | field `x` of chore `n` in the snapshot |
| `Q.runs(chore?, window?, statuses?)` | the past-runs query, newest first |
| `Q.run(id)` | one run record |
| `Q.artifact(id, name)` | one of `definition.md`, `transcript.jsonl`, `stdout.log`, `stderr.log`, `errors.log` |
| `Q.stateSize()` | size on disk of the state directory |
| `A.name(args)` | an action from Domain reference 4 |
| **derived** | computed by the surface from the fields above. Never stored and never sent back. |

Hard rules that apply everywhere:

1. Surfaces render the snapshot and query results **only**. There is no other data source, and no surface writes to the definitions.
2. Colour reinforces meaning and never carries it alone. Every state has an icon shape or a word that stands on its own in monochrome.
3. Secrets never appear. Secret **names** may appear, in the dry-run plan only.
4. Every screen shows how old its data is.
5. Every action that can be refused shows the refusal with all of its causes, and says for each cause whether it can be forced.

---

## 1. Shared foundation

### 1.1 Polling and freshness

| Surface | Poll `S` | Extra queries | Stale threshold |
|---|---|---|---|
| Mac app | every 2 s while any window is visible; every 15 s when hidden | the visible view's queries, re-run on each poll | age > 6 s |
| Menu-bar item | every 15 s, plus once immediately when the menu opens | none | age > 60 s |
| TUI | every 2 s | the visible screen's queries | age > 6 s |
| CLI | once per invocation | as requested | n/a |

**Wire.**

- "Age" = local clock minus `S.at`. Keep the last good snapshot. If a poll fails, keep rendering the old snapshot and switch to the *snapshot failed* state (section 9).
- There are two different freshness facts. Never merge them:
  - **Data age**: how old this surface's view is, from `S.at`.
  - **Scheduler health**: `S.scheduler.last_tick`, `.stale`, `.installed`.

  One tells the operator "my view is old". The other tells them "the machine stopped ticking". They must never look the same.
- On wake from sleep, poll immediately. Don't wait for the timer.

### 1.2 Attention items (derived)

Every surface ranks the same list. Compute it once per snapshot with this function:

```
attention(S, runsQuery) -> [Item]
Item = { level: sys|alert|warn|info, subject, status, text, since,
         chore?, run_id?, scope?, notification_id?, primary_action? }

sys:
  S.scheduler.installed == false         -> "Scheduler not installed"   action: install
  S.scheduler.stale == true              -> "Scheduler stale"           action: install
  each line in S.warnings                -> the line, verbatim          action: open System
alert:
  chore.paused_by starts with breaker    -> "Paused by breaker"         action: resume
  any scope dimension usage >= ceiling   -> "At ceiling"                action: open Usage
  chore.last_run.status in FAILED, TIMED_OUT, BUDGET_EXCEEDED, INTERRUPTED
     (skipped if the chore is breaker-paused; the breaker item covers it)
                                         -> status + reason             action: open run
  chore.invalid != none                  -> "Invalid" + first violation action: open chore
  unread alert notification with no item above for its chore
                                         -> notification text           action: dismiss
warn:
  chore.running and running long (1.4)   -> "Running long"              action: kill
  any scope dimension >= 80% and < 100%  -> "Ceiling near"              action: open Usage
  chore.last_run.status in MISSED, SKIPPED_*, DEFERRED_BATTERY
                                         -> status (+ count) + reason
  chore.last_run.status in OFFLINE, KILLED -> status + reason
  latest run of a chore has truncated == true -> "Truncated"
  (optional) trend flag > 2x, see 1.4    -> "Out of pattern"
info:
  each unread info notification          -> text                        action: dismiss
```

- Order: level, then the order above, then newest `since` first.
- If an item's chore has an unread alert notification, attach it as `notification_id`. It then shows as "unread alert" on the item instead of as a separate row.
- **Clearing.** An item vanishes when its condition is no longer true in `S`. Dismissing a notification only removes the "unread" marker. There is no acknowledge for failed runs (open question Q1).

### 1.3 Status vocabulary

Implement this once and use it everywhere. The TUI glyph is the monochrome carrier in the terminal. The app icon shape plus the status word is the carrier in the GUI.

| Status / state | App icon (Phosphor) | Timeline mark | Tone | TUI glyph / word |
|---|---|---|---|---|
| SUCCEEDED | check-circle | filled dot | ok (neutral-500) | `SUCCEEDED` |
| FAILED | x-circle (fill) | filled diamond | alert (accent-400) | `FAILED` |
| TIMED_OUT | timer (fill) | filled diamond | alert | `TIMED_OUT` |
| BUDGET_EXCEEDED | coins (fill) | filled diamond | alert | `BUDGET_EXCEEDED` |
| INTERRUPTED | lightning-slash | filled diamond | alert | `INTERRUPTED` |
| KILLED | hand-palm | hollow ring | warn (neutral-300) | `KILLED` |
| OFFLINE | wifi-slash | hollow ring | warn | `OFFLINE` |
| MISSED | moon | hollow ring | warn | `MISSED xN` |
| SKIPPED_OVERLAP | stack | hollow ring | warn | `SKIPPED_OVERLAP` |
| SKIPPED_PAUSED | pause-circle | hollow ring | warn | `SKIPPED_PAUSED` |
| SKIPPED_CEILING | gauge | hollow ring | warn | `SKIPPED_CEILING` |
| SKIPPED_OFFLINE | wifi-slash | hollow ring | warn | `SKIPPED_OFFLINE` |
| DEFERRED_BATTERY | battery-warning | hollow ring | warn | `DEFERRED_BATTERY` |
| INVALID | file-x (fill) | filled diamond | alert | `INVALID`, ST `X` |
| RUNNING | circle-notch (spinning) | bar from start to now | run (accent-300) | `RUNNING`, ST `*` |
| PENDING | hourglass | bar | run | `PENDING` |
| chore paused by breaker | pause-circle (fill) | lane hatched from the pause | alert | ST `B` |
| chore paused by operator | pause-circle | lane hatched | warn | ST `P` |
| chore disabled in git | minus-circle | lane name struck through, row at 55% | faint | ST `-` |
| global pause | pause (toolbar) | future ticks dimmed | banner | banner `\|\|` |

Status words are shown exactly as the domain spells them. The app may render them in title case in prose ("Budget exceeded"), but tags keep the domain spelling.

### 1.4 Derived metrics

| Metric | Formula | Inputs | Used by |
|---|---|---|---|
| Running long | elapsed > 3x median wall time of the last 10 SUCCEEDED runs, and elapsed > 60 s. Not flagged with fewer than 3 successes. | `S.chore.running.started`, `Q.runs(chore, statuses=[SUCCEEDED], limit 10)` | Needs you, TUI, menu Running |
| Near ceiling | usage / ceiling >= 0.80 in any dimension | `S.usage[scope][dim]` | Needs you, Usage, inspector |
| At ceiling | usage / ceiling >= 1.00 | same | same |
| Trend ("against your usual") | sum of the last 24 h per scope and dimension, divided by the median of the same 24 h window on each of the previous 7 (or 28) days. Flag > 2x. | `Q.runs(window=8d or 29d)`; sum `usage` by scope and dimension | Usage |
| Per-chore 24h cpu/disk | sum of `cpu_seconds`, `disk_bytes` over `Q.runs(chore, 24h)` | runs | inspector, TUI Chore |
| Binding ceiling | the smallest remaining (ceiling - usage - declared budget) across the scopes that apply | dry-run plan | dry-run sheet |

Subscription billing counts toward tokens and turns and never toward usd. Show usd as "subscription", never as `$0.00`.

### 1.5 The refusal model

`A.run_now(chore, force?)` is admitted or refused. Refusals list **every** cause:

| Cause | Forceable | Shown text (template) | Offered next step |
|---|---|---|---|
| global pause | no | `Paused "<reason>" since <time>.` | Resume all |
| breaker pause | no | `Paused by breaker: <reason>.` | Resume... |
| operator pause | no | `Paused by you: <reason>.` | Resume |
| ceiling | no | `<scope> <dim>: <used> used + <budget> budget would cross <ceiling>` | Dry run |
| invalid | no | each violation | Open chore |
| disabled | no (Q2) | `Disabled in git.` | -- |
| overlap | yes | `The previous run has been going since <t> (<elapsed>).` | Force run, Kill |
| battery | yes | `On battery; defer_on_battery is set.` | Force run |
| offline | yes | `Backend <name> unreachable.` | Force run |
| no snapshot | no | `Status could not be read.` | -- |

**Force** is offered only when every cause is forceable. Use the admission verdict from `A.dry_run` to pre-check before calling `A.run_now`. The server's answer is final. If it refuses after a clean dry run, show the server's causes.

### 1.6 Time and number formatting

- Local time throughout. The timezone is printed once in CLI headers.
- Today: `HH:MM:SS` (or `HH:MM` in dense UI). Earlier this week: `Fri 08:45`. Older than 7 days: `2026-09-14 09:00`.
- Durations: `41s`, `5m 10s`, `4h 53m`.
- Tokens use thousands separators. usd uses 2 decimals with `$` in the GUI and no `$` in the CLI.
- `--` means no value or no ceiling. It never means zero.

### 1.7 Deep links

A URL scheme, so the menu bar, notifications, the Dock and the CLI can all land the app on an object:

| URL | Lands on |
|---|---|
| `chores://needs` | Needs you |
| `chores://chore/<name>` | Needs you (or All chores) with `<name>` selected in the inspector |
| `chores://run/<run_id>[?tab=transcript\|errors\|stdout\|stderr\|definition\|compare]` | Run view |
| `chores://usage[?scope=<scope>]` | Usage, scope highlighted |
| `chores://inbox` | Inbox |
| `chores://system` | System |
| `chores://pause` | Pause-all sheet |
| `chores://kill/<chore>` | Kill confirmation sheet for that chore's running run |

If a sheet is open when a link arrives, queue the link. Never discard the operator's sheet.

---

## 2. Mac app

### 2.1 Window anatomy

```
+--------------------------------------------------------------------------+
| (o)(o)(o)  View title / subtitle        [freshness pill]  [Pause all]    |  toolbar, 52px
+-----------+--------------------------------------------+-----------------+
| Sidebar   | Banners (pause / scheduler / snapshot)     | Inspector       |
|  Needs you| ------------------------------------------ | (selected chore)|
|  All      | View content                               |                 |
|  Usage    |                                            |                 |
|  Inbox    |                                            |                 |
|  System   |                                            |                 |
|  --       |                                            |                 |
|  Backends |                                            |                 |
+-----------+--------------------------------------------+-----------------+
```

Column widths: 216 / flexible / 330. Below 1,220 px of window width the inspector turns into a slide-over from the right, opened by selecting a chore and closed with its X button or `Esc`. The sidebar narrows to 188.

The app is **single-instance**. A second launch focuses the existing window.

### 2.2 Toolbar

**Use.**

- The title and subtitle name the view and summarise it, for example "Needs you -- 3 need you, 5 warnings, 1 message".
- The **freshness pill** normally reads "Updated 1s ago - tick 41s ago" in quiet grey. When something is wrong it turns into a tinted pill: "Last tick 4h 53m ago", "Scheduler not installed", or "Data from 14:05:12. Status unreadable".
- **Pause all** is the kill switch. While a pause is in effect, the same button reads **Resume all**.

**Wire.**

| Element | Source | Action |
|---|---|---|
| Title/subtitle | view name; counts from `attention()` | -- |
| Freshness pill | `now - S.at`; `S.scheduler.last_tick`, `.stale`, `.installed`; poll error | -- |
| Pause all | `S.paused` | opens Pause-all sheet -> `A.pause_global(reason)` (+ optional `A.kill` per running run) |
| Resume all | `S.paused` | opens Resume-all sheet -> `A.resume_global()` |

### 2.3 Sidebar

**Use.** It switches views. Badges count what matters: Needs you = sys + alert items (or the warn count if there are none), All chores = the total, Inbox = unread, System = `!` when something is wrong. Under **Backends, 24h** there is one mini bar per backend, showing its binding dimension against its ceiling.

**Wire.**

| Element | Source |
|---|---|
| Needs you badge | `attention()` counts; badge is accented when > 0 |
| All chores badge | `len(S.chores)` |
| Inbox badge | count of `S.notifications` where `read == false` |
| System badge | `!` if `S.scheduler.installed == false`, `S.scheduler.stale`, or `S.warnings` is non-empty |
| Backend bars | `S.usage[backend]`: show usd if it has a usd ceiling, else turns if it has a turns ceiling, else tokens with "no ceiling". Accent fill at >= 80%. |
| Footer | static: "Definitions are read-only here. Edit them in git." |

### 2.4 Banners

At most one of each, stacked in this order, above any view:

| Banner | Condition | Button -> action |
|---|---|---|
| Status could not be read | the last poll failed | none (actions are held) |
| The scheduler is not installed | `S.scheduler.installed == false` | Install -> `A.install()` |
| The scheduler has stopped ticking | `S.scheduler.stale` | Reinstall -> `A.install()` |
| Everything is paused: "reason" | `S.paused != none` | Resume all -> Resume-all sheet |

### 2.5 Needs you (default view)

**Use.**

- Things needing attention appear in three groups:
  - **Stopped until you act** -- system problems and alerts.
  - **Did not happen, or heading for a limit** -- warnings; these clear on their own.
  - **Messages** -- posted by chores.
- Each row shows an icon, the chore, a status tag, a plain-language explanation, a time, and at most one primary button:

  | Item | Button |
  |---|---|
  | breaker pause | Resume |
  | failed run | Open run |
  | running long | Kill... |
  | message | Dismiss |

- Clicking a row selects its chore in the inspector. A row for the scheduler or a warning opens System instead, and a row for a scope with no chore opens Usage.
- When the list is empty, the view reads **Nothing needs you.** with one summary line underneath.
- Below the list is the **Today** timeline (2.6).

**Wire.**

| Element | Source | Action |
|---|---|---|
| Rows | `attention()` | -- |
| "unread alert" tag | `item.notification_id` | -- |
| Resume | -- | Resume sheet if breaker (2.12), else `A.resume(chore)` directly |
| Open run | `item.run_id` = `S.chore.last_run.run_id` | Run view |
| Kill... | `S.chore.running.run_id` | Kill sheet |
| Dismiss | `item.notification_id` | `A.dismiss(id)` |
| Quiet line | `len(S.chores)`, count of running chores, earliest `next_due` | -- |

Copy rule: explain every status in words a tired operator reads at a glance. Examples:

- OFFLINE: "The gateway was unreachable, so it failed fast. There was no network; nothing is wrong with the chore."
- MISSED: "missed x2 while asleep 01:10 to 07:55; catch_up off, so not replayed".

### 2.6 Today timeline

**Use.** One lane per chore, from 00:00 to 24:00. A vertical accent line marks now.

- **Marks:**
  - filled dot = succeeded
  - filled diamond = stopped or failed
  - hollow ring = did not run
  - accent bar = running (grows until it ends)
  - thin tick = due later today
- **Lanes:**
  - a paused lane is hatched from the moment it paused, and its future ticks are dimmed
  - an invalid chore's future ticks are dimmed and their tooltip says "will not run"
  - a disabled chore's name is struck through
- **Sleep:** a diagonal hatch across all lanes shows when the laptop was asleep.
- Hover a mark for its status and time. Click it to open the run. Click a lane name to select the chore.

Lane order: the same ranking as Needs you (the chores with attention items first), then the others by name. With 40+ chores, the timeline shows the chores that have attention items plus the running ones, then a "Show all N" disclosure.

**Wire.**

| Element | Source |
|---|---|
| Past marks | `Q.runs(window=today 00:00..now)` across all chores, one mark per record at `started` (non-run outcomes at their slot time) |
| Running bar | `S.chore.running.started` to now |
| Future ticks | expand each chore's `schedule` (cron, local time) from now to 24:00. Dimmed if `paused_by`, `invalid` or `S.paused` is set. None if `enabled == false`. |
| Pause hatch | from the breaker notification's timestamp, or from the first SKIPPED_PAUSED record, whichever is known |
| Sleep band | **data gap.** The domain doesn't record sleep intervals. v1 derives the band from MISSED records that carry a window in their reason text. If no window is known, draw nothing. |
| Now line | local clock |

### 2.7 All chores

**Use.** A table of every chore: state icon, name with its state in words, kind/backend, last run (icon, status, time), last success, next. There is a filter field (name, kind, backend) and a segmented control: All / Attention / Running / Paused / Disabled. Click a row to select it. Disabled rows are dimmed and their next reads "never".

**Wire.**

| Column | Source |
|---|---|
| State icon | `running` -> spinner, `paused_by` -> pause-circle, `invalid` -> file-x, `enabled == false` -> minus-circle, else an empty circle |
| State word | as above: "running 5m 10s", "paused by breaker", "invalid", "disabled in git", "enabled" |
| Kind / backend | `kind`, `backend` |
| Last run | `last_run.status`, `.started` |
| Last success | `last_success.started` |
| Next | `enabled == false` -> never; `invalid` -> will not run; `paused_by` or `S.paused` -> held; else `next_due` |
| "Attention" filter | chore has any non-info item in `attention()` |

Default sort: attention rank, then name. Clicking a column header sorts by it (v1 can ship without this).

### 2.8 Inspector (selected chore)

**Use.** From top to bottom:

1. Name, "kind on backend - schedule", and state tags.
2. If invalid: a tinted box listing every violation.
3. Action buttons. The most relevant one is outlined as primary: Kill if it's running, Resume if it's paused, otherwise Run now.
4. Facts: next due, budget, running since.
5. Two pinned cards, **Last success** and **Last failure**. Click either to open that run.
6. Ceiling meters, for chores that have their own ceiling.
7. Up to 7 recent runs. Click one to open it.
8. A footer: the definition is read-only; edit it in git.

**Wire.**

| Element | Source | Action |
|---|---|---|
| Tags | `enabled`, `invalid`, `paused_by`, `running`, `S.paused` | -- |
| Violations | `S.chore.invalid` | -- |
| Kill | `running` | Kill sheet -> `A.kill(run_id)` |
| Resume | `paused_by` | 2.12 |
| Run now | -- | `A.dry_run` pre-check -> Refusal sheet or `A.run_now` |
| Dry run | -- | `A.dry_run(chore)` -> Dry-run sheet |
| Pause | shown only if not paused and enabled | Pause-chore sheet -> `A.pause(chore, reason)` |
| Next due | as in 2.7 | -- |
| Budget | **not in the snapshot.** Show the value from the latest run's `definition.md` snapshot, labelled with its rev, or "shown in dry run". | -- |
| Last success / failure | `last_success`, `last_failure` | Run view |
| Ceiling meters | `S.usage[chore]` when present | -- |
| Recent runs | `Q.runs(chore, limit=7)` | Run view |

### 2.9 Run view

**Use.**

- **Header:** a back button, a breadcrumb with the run id, a large status icon and status, and the reason.
- **Budget bar:** for a run that exceeded its budget, a bar with a mark at the budget, so you can see how far over it went.
- **Facts grid:** started, ended, wall time, backend, model, billing, tokens in/out, turns, CPU, disk, exit code, definition rev (with "uncommitted" for `-dirty`), truncated.
- **Tabs:**
  - **Transcript N** -- grouped by turn. Each turn has a header ("Turn 3 - 69 lines, 23 tool calls"). Expand one turn or all. Search filters lines and opens the matching turns. Each line shows its line number, a type chip and a compact JSON remainder.
  - **Errors / Stdout / Stderr** -- plain text with line numbers. An empty file says "Empty".
  - **Definition** -- the exact `definition.md` the run used, with its rev.
  - **Compare** -- a side-by-side diff against the chore's last successful run (a picker chooses another run), with changed lines highlighted. If the two are identical it says "definition identical -- the difference is not in the definition".

**Wire.**

| Element | Source |
|---|---|
| Header, facts | `Q.run(id)`: status, reason, started, ended, backend, model, billing, usage.*, exit_code, definition_rev, truncated |
| Budget bar | usage vs the budget from `Q.artifact(id, definition.md)`. Show it only when a budget is declared for the exceeded dimension. |
| Tab counts | line counts of each artifact (count on load; don't read whole files into memory) |
| Transcript | `Q.artifact(id, transcript.jsonl)`, streamed and virtualised. Group by a top-level `turn` key **if present** (open question Q7). Otherwise show flat, numbered lines. Lines that fail to parse are shown raw with a `!json` chip. |
| Search | a substring over raw lines, done by the backend for large files |
| Errors/Stdout/Stderr | the matching artifact, as-is |
| Definition | `Q.artifact(id, definition.md)` |
| Compare | `Q.artifact(other_id, definition.md)`, where other = `S.chore.last_success.run_id` by default. A line diff with 3 lines of context. |
| Truncated | when `truncated == true`, every tab label gets a "(truncated)" suffix and every pane ends with a notice |
| Running run | re-query every poll and follow the tail until the user scrolls up |

### 2.10 Usage

**Use.**

- **Scope cards** -- global, each backend, each chore with its own ceiling. Each card has one meter per dimension, with a tick at 80%; the fill turns accent at 80% or more. Dimensions without a ceiling show the value alone. Subscription backends say "subscription, not billed per call" for usd.
- **Against your usual** -- one row per scope and dimension. Seven small bars show the same 24h window on each previous day, and a highlighted eighth bar shows the last 24h. Each row gives today's value against the median, and a multiplier; rows above 2x are accented and sorted first.

**Wire.**

| Element | Source |
|---|---|
| Cards | `S.usage` (`global`, each backend, each chore with a ceiling): usage and ceiling per dimension |
| Trend rows | derived (1.4) from `Q.runs(window=8 days)`. The window toggle (7d/28d) is v1.1. |
| Click chore card | select that chore in the inspector |

### 2.11 Inbox and System

**Inbox. Use.** A list of notifications, newest first. An unread one has a dot, bold text and an alert or message icon. Click a notification to open its run, or its chore if it has no run. It has a **Dismiss** button and **Mark all read**.
**Wire.** Items from `S.notifications`. Dismiss calls `A.dismiss(id)`, and Mark all read calls `A.dismiss` once for each unread id.

**System. Use.** Facts (scheduler, ledger rows, state directory size, global pause, warnings), then four action rows, then a link that opens the TUI.

**Wire.**

| Row | Source / action |
|---|---|
| Scheduler | `S.scheduler.installed`, `.tick_interval`, `.last_tick`, `.stale` |
| Ledger | `S.scheduler.ledger_rows` |
| State directory | `Q.stateSize()`, queried when System opens |
| Warnings | `S.warnings`, verbatim |
| Validate | `A.validate()` -> a toast with the count, or a sheet listing the violations |
| Install | `A.install()`, no confirmation. It is idempotent and repairs an interval mismatch. |
| Uninstall... | Confirm sheet -> `A.uninstall()` |
| Prune... | Confirm sheet -> `A.prune()`. Report the size before and after using `Q.stateSize()`. |
| Open the TUI | launches the terminal dashboard (3.3) |

### 2.12 Sheets

All sheets drop from the toolbar, cover the content with a dimmed layer, and close on Cancel, `Esc` or a click outside. Only one sheet is open at a time.

| Sheet | Opened by | Content | Buttons -> action |
|---|---|---|---|
| Refusal | Run now, when refused | one row per cause with a tag, "can be forced" or "cannot be forced", plus a note | Cancel; Dry run; **Force run** (only if all causes are forceable) -> `A.run_now(force=true)`; **Resume...** (if a breaker cause) |
| Dry run | Dry run, or the refusal's Dry run | backend and model, budget, secret **names**, each applicable scope's usage/ceiling, the verdict (admit/refuse + causes, binding ceiling) | Close. Calls `A.dry_run`; nothing executes. |
| Kill | Kill... | how long it has been running and since when; "ends KILLED" | Cancel; **Kill run** -> `A.kill(run_id)` |
| Resume (breaker) | Resume on a breaker-paused chore | the failure sequence, which slot will be admitted next | Cancel; Dry run first; **Resume** -> `A.resume(chore)` |
| Pause chore | Pause | reason field (required); "the run in progress continues" | Cancel; **Pause** -> `A.pause(chore, reason)` |
| Pause all | toolbar, Dock menu, `chores://pause` | note, reason field (required), "Also kill what is running now (names)" checkbox | Cancel; **Pause all** -> `A.pause_global(reason)`, then `A.kill` for each running run if the box is checked |
| Resume all | toolbar or banner | the reason and since-time; the next 3 slots due | Cancel; **Resume all** -> `A.resume_global()` |
| Confirm (Uninstall, Prune) | System | one sentence on the consequence | Cancel; the verb |

**What the operator sees while an action runs, and after:**

- **Sent:** a toast at the bottom centre says the action was sent ("Kill signal sent to log-brand-sweep").
- **Done:** a second toast confirms it once the next snapshot or query shows the result ("log-brand-sweep ended KILLED").
- **Refused or failed:** the refusal sheet opens (for run now), or an error toast shows the server's text verbatim.
- Toasts disappear after 3 s. Never use a toast for a refusal of run now; that always gets the sheet.

### 2.13 Keyboard

The app is keyboard-first. The mouse is a convenience.

| Keys | Action |
|---|---|
| Cmd-1 .. Cmd-5 | Needs you, All chores, Usage, Inbox, System |
| Up / Down | move the selection in the current list |
| Return | open (row -> inspector focus; run row or mark -> Run view) |
| Esc / Cmd-[ | back / close sheet / close slide-over |
| Cmd-F | focus the filter or search field |
| Cmd-R | Run now (selected chore) |
| Cmd-Shift-R | Dry run |
| Cmd-. | Kill (selected chore's running run), with the confirm sheet |
| Cmd-P / Cmd-Shift-P | Pause chore / Pause all |
| Cmd-U / Cmd-Shift-U | Resume chore / Resume all |
| Cmd-D | Dismiss (selected item's notification) |
| Ctrl-Tab / Ctrl-Shift-Tab | next / previous run tab |
| Cmd-C (in the Run view) | copy the run id |
| Cmd-T | Open in Terminal (TUI) |

Every button tooltip shows its shortcut. Focus rings use `:focus-visible` (2px accent).

---

## 3. Dock tile

### 3.1 Use

- **Click:** opens the app window, or brings it to the front if it is already open. A second window is never created.
- **Right-click:**
  ```
  3 need you                 (disabled header)
  -----
  Open chores
  Open in Terminal (TUI)
  -----
  Pause All...               (or "Resume All" while paused)
  Validate Definitions
  -----
  Quit
  ```
- There is no Dock badge. The menu-bar item is the one glance surface (see Rejected alternatives in the design doc).

### 3.2 Wire

| Item | Action |
|---|---|
| Header | `attention()` count |
| Open chores | activate or create the window |
| Open in Terminal (TUI) | 3.3 |
| Pause All... | open the app and deep link `chores://pause` |
| Resume All | `A.resume_global()` directly. It is safe, and the operator set the pause. |
| Validate Definitions | `A.validate()` -> a macOS notification with the result if the app window is hidden, otherwise a toast |
| Quit | quit the app. The scheduler keeps running; the app is only a viewer. |

### 3.3 Opening the TUI

Launch the user's default terminal with `chores dash` (Terminal.app via a `.command` file or AppleScript, or iTerm2 if it is the default handler). If a TUI launched by the app is already running, focus that terminal window instead of starting a second one. Track this with a PID/lock file written by `chores dash`.

---

## 4. Menu-bar item (Glance)

### 4.1 Use

The title answers "does anything need me?" without opening anything.

| State | Title |
|---|---|
| All quiet (running counts as quiet) | icon only |
| Unread messages only | icon + `1` |
| Warnings | icon + `~5` |
| Alerts | alert icon + `!3` |
| System problem line | alert icon + `!!1` |
| Global pause | pause icon + `PAUSED` (+ any count) |
| Scheduler stale | clock icon + `STALE` |
| Not installed | prohibit icon + `OFF` |
| Snapshot failed / menu data > 60 s old | hollow icon + `?` |

The dropdown lists the attention items (alerts one by one, warnings in a submenu, messages one by one), what is running, usage in a submenu, then Open Dashboard, Mark All Messages Read, Pause All..., and Quit. Full layouts for every state are in `chores-ux-design.md`, section 3.

### 4.2 Wire

- Precedence for the title: `?` > `OFF` > `STALE` > `PAUSED`, then the worst count, `!!n` > `!n` > `~n` > `n`. Scheduler items are excluded from the count, because the word already carries them.
- The menu is a **native NSMenu**: plain text items, separators, submenus, checkmarks. No custom views, and no colour inside the menu.
- Rule: the menu never performs an action that can be refused or needs confirmation. Such items deep link into the app ("Open in Dashboard", "Kill in Dashboard...", "Pause All..." -> `chores://pause`). In-place actions are limited to `A.dismiss` and `A.resume_global`.
- The menu-bar item is a separate lightweight process (a login item). It stays up when the app window is closed.

---

## 5. macOS notifications

| Posted when | Title / body | Click |
|---|---|---|
| A notification with `level == alert` appears in `S.notifications` (breaker pause, statuses listed in a chore's `notify_on`) | chore name / notification text | `chores://run/<run_id>`, or `chores://chore/<name>` if it has no run |
| The scheduler becomes stale or uninstalled (edge-triggered, once per episode) | "chores scheduler stopped" / "Last tick 09:12. Nothing is firing." | `chores://system` |
| A system warning line appears | "chores warning" / the line | `chores://system` |

- Info notifications post **no** system notification (Q6). They only change the menu-bar title.
- De-duplicate by `notification.id`. On first launch, don't post for notifications that already exist.
- Which process posts them: the menu-bar item. It is always running and already polls.

---

## 6. Terminal dashboard (TUI)

The TUI is the app's twin for the terminal: same data, same attention list, same actions, same refusals, keyboard only. Use it over ssh, in a tmux pane, or whenever you are already in a shell. Where this section says "same as the app", the Wire rules in section 2 apply unchanged.

### 6.1 Launching and the frame

**Use.**

- Start it with `chores dash` in any terminal. You can also open it from the Dock menu ("Open in Terminal (TUI)"), from System > "Open the terminal dashboard", or with Cmd-T in the app.
- The first frame appears at once: the tab bar with `..` in place of counts, and `reading status...` on row 2. Then the Needs screen paints in place. If the read takes longer than 2 s, row 2 adds the elapsed time and the last known ledger row count.
- `q` quits from anywhere, with no confirmation, because nothing is lost. If the app launched the terminal, the terminal window closes too.

The frame is the same on every screen, at any size:

```
row 1        tabs + snapshot clock
row 2        context line, or a MODE BANNER (reverse video)
rows 3..H-2  content
row H-1      message line (result of the last action)
row H        key hints for this screen (? for all keys)
```

| Size | Layout |
|---|---|
| 80x24 (minimum) | a single column. On Needs, the detail pane sits under the list. Run shows one artifact tab at a time. |
| 160x48 and wider | a split view. Needs gets a detail pane on the right with notifications, recent runs and actions. Run shows the transcript on the left and another tab on the right. Lists gain columns. |
| smaller than 80x24 | a single centred line: `chores needs 80x24 (now 72x20)`. Polling continues. |

**Wire.**

| Rule | Detail |
|---|---|
| Toolkit | a Textual-class Python full-screen app. Modal overlays, scrolling panes and mouse support are provided by the toolkit. |
| Single instance | `chores dash` writes a lock/PID file. If one is already running from the Launcher, the Launcher focuses that terminal instead of starting another. A second `chores dash` typed by hand in another shell is allowed; each instance polls on its own. |
| Resize | re-lay out on SIGWINCH, keeping the cursor and scroll position of every screen |
| Colour | truecolor if available, 256 colours as a fallback. `NO_COLOR` or a dumb terminal switches to monochrome; every state keeps its glyph or word (6.13). |
| Terminal state | alternate screen buffer; restore the terminal on exit or crash |
| Polling | as in 1.1: `S` every 2 s, plus the visible screen's queries. `Ctrl-r` polls now. |

### 6.2 Header, banners, message line, key hints

**Use.**

- **Row 1**, for example:

  ```
  chores [1 Needs !3] 2 Chores 9 3 Runs 4 Usage 5 Inbox 3 6 System   14:05:12 +1s
  ```

  The active tab is bracketed and in reverse video. Needs shows its worst count: `!!n`, `!n`, `~n` or `n`. Inbox shows the unread count. The right end is the snapshot time and its age. When the age passes 6 s it becomes `DATA OLD +47s` in reverse video, and content dims.
- **Row 2** is a mode banner when one applies, in this priority:

  ```
  !! SNAPSHOT FAILED: <error>. Showing 14:05:12. Retrying every 2s.
  !! SCHEDULER NOT INSTALLED -- nothing fires on schedule.  6 System > install
  !! SCHEDULER STALE -- last tick 09:12:04 (4h53m). Nothing is firing.  6 System
  || GLOBAL PAUSE "on a flight" since 06:40 -- nothing starts.  U resume
  ```

  Otherwise it is context: the summary on Needs, the counts and sort on Chores, the breadcrumb on Chore and Run, the filter or search while typing.
- **Row H-1** shows the result of your last action. The prefix tells you what happened:

  | Prefix | Meaning |
  |---|---|
  | `...` | in flight |
  | `ok:` | done |
  | `refused:` | refused by admission |
  | `failed:` | the action errored |

- **Row H** lists the 6-8 most useful keys for the focused screen. `?` shows them all.

**Wire.**

| Element | Source |
|---|---|
| Tab counts | `attention()` worst level; `len(S.chores)`; the unread count |
| Clock | `S.at`, and `now - S.at` |
| Banners | as the app banners (2.4), same conditions and priority |
| Message line | the action result, replaced by the next action. A "cleared: <item>" line shows for 5 s when a Needs row disappears. |

### 6.3 1 Needs

**Use.** The landing screen: the ranked attention list.

- Columns: `LV` (`!!` `!` `~` `i`), `CHORE`, `WHAT`, `SINCE`. `>` marks the cursor row.
- The detail pane describes the selected item's object: state, last run, last ok, next due, schedule, and its notification (`* unread alert n-0412`). At 160 wide it also lists the chore's notifications, recent runs and available actions.
- `Enter` opens the item's object:

  | Item | Opens |
  |---|---|
  | run-status row | Run, on the Transcript tab |
  | INVALID | the Chore screen |
  | ceiling | Usage |
  | `!!` row | System |
  | message | the linked run, else the chore |

- Act on the row directly:

  | Key | Action |
  |---|---|
  | `u` | resume |
  | `K` | kill |
  | `r` | run now |
  | `t` | dry run |
  | `d` | dismiss its notification |
  | `c` | open the chore |
  | `o` | open the chore's last run |

- An empty list shows `Nothing needs you.` and one summary line.

**Wire.** Rows come from `attention()` (1.2), rendered verbatim. The detail pane comes from `S.chore[name]`, plus `Q.runs(chore, limit 6)` at 160 wide. When the cursor's row clears, the cursor keeps its index.

### 6.4 2 Chores

**Use.**

- **ST glyphs:**

  | Glyph | Meaning |
  |---|---|
  | `*` | running |
  | `B` | paused by breaker |
  | `P` | paused by you |
  | `X` | invalid |
  | `-` | disabled in git |
  | (blank) | enabled |

- Columns at 80 wide: ST, NAME, KIND/BACKEND, LAST (status word), AT, NEXT. At 160 wide: plus LAST OK, SCHEDULE and REASON.
- `/` filters. Free text matches the name. Tokens narrow it further: `state:paused|invalid|disabled|running`, `kind:agent`, `backend:gateway`, `last:FAILED,TIMED_OUT`. Row 2 shows `filter: ... (3 of 9)`. `Esc` clears it.
- `s` cycles the sort: attention (default) -> name -> next due -> last run. Disabled chores sink to the bottom except in the name sort.
- `Enter` opens the Chore screen, `o` the last run. `r`, `t`, `p`, `u` and `K` act on the row.

**Wire.** Same sources as the app's All chores (2.7). NEXT reads `disabled`, `--` (invalid), `paused`, or `(not inst.)` when the scheduler is not installed; otherwise `next_due`. A legend prints under the list while it is shorter than the screen.

### 6.5 Chore (drill-down)

**Use.**

- **Header:** name, kind / backend / model, state, schedule, next.
- **limits:** the budget, from the last run's definition snapshot and labelled with its rev.
- **24h:** usage against the chore's own ceiling, with `~` or `!` marks.
- **Pinned lines:** `last ok` and `last bad` are always visible, so you never need to scroll for them. Enter on either opens that run.
- **Run history:** STARTED, STATUS, WALL, TOKENS, TURNS, REV. At 160 wide it adds TOK IN/OUT, CPU, DISK and REASON.
- The footer shows the history filter and the row count.

**Wire.**

| Element | Source |
|---|---|
| Header | `S.chore` |
| Limits | `Q.artifact(latest run, definition.md)` |
| 24h | `S.usage[chore]` |
| Pinned lines | `last_success`, `last_failure` |
| History | `Q.runs(chore, 30d)`; `/` changes the window and status set |
| 160-wide sum row | derived (1.4) |

### 6.6 3 Runs

**Use.** A cross-chore run list, newest first. The query shows on row 3; the default is `window 24h, status all`.

| Preset | Query |
|---|---|
| `F2` | failures, 30 days |
| `F3` | budget and timeout, 30 days |
| `F4` | non-runs, 24 hours |

`Esc` returns to the default. `Enter` opens the run, `c` its chore, and `y` copies the run id.

**Wire.** `Q.runs(window, statuses)`. The ledger is never pruned, so month queries keep working after a prune. Rows whose directory was pruned show `(pruned)` in REV and open with header facts only.

### 6.7 Run (drill-down)

**Use.**

- **Header, 4 lines:**
  1. status and reason
  2. started -> ended (wall), kind, backend / model / billing
  3. tokens in/out, turns, cpu, disk, exit code, usd (`-- (subscription)` where it applies)
  4. rev (`-dirty` spelled out as "uncommitted changes") and truncated
- **Tab bar:** `[Transcript 1240] Errors 1 Stdout 3 Stderr 0 Definition Compare`. `Tab` and `Shift-Tab` move between tabs; an empty tab is dimmed.
- **Transcript:** one row per JSON line, `+` collapsed and `-` expanded.

  | Key | Action |
  |---|---|
  | `j` / `k` | move the line cursor |
  | `Enter` | expand the line to pretty JSON in place |
  | `z` | expand or collapse every line |
  | `/` | search raw text; `n` / `N` step through matches ("line 880 (17 matches)") |
  | `g` / `G` | top / bottom (`G` also re-follows a running run) |
  | `:880` | jump to line 880 |

  A line that fails to parse is shown raw with `!json`.
- **Errors / Stdout / Stderr:** numbered plain text. `w` toggles wrap; an empty file reads `(empty)`.
- **Definition:** `definition.md @ <rev>`, verbatim.
- **Compare:** a unified diff against the last success, with `-` and `+` prefixes and 3 lines of context. `=` jumps here from any tab; the picker chooses another run. Identical snapshots read "definition identical -- difference is not in the definition".
- At 160 wide the transcript stays on the left, and `Tab` switches the right-hand pane between the other tabs.
- `v` opens the current artifact in `$PAGER`. `y` copies the run id (OSC 52, so it works over ssh). `K` kills the run if it is still running.

**Wire.** Same sources as the app's Run view (2.9). Artifacts are read lazily and windowed, never loaded whole. A running run's artifacts are re-read every poll, and the view follows the tail until the user scrolls up. Truncated records add `(trunc)` to every tab label and `-- truncated at disk cap --` at the end of each pane.

### 6.8 4 Usage

**Use.**

- **Scope table:** global, each backend, and each chore with a ceiling. For each of tokens, usd and turns: used/ceiling and a percentage. `~` marks near (>= 80%), `!` marks at ceiling, and `--` means no ceiling or not billed in that dimension.
- **Band below:** the last 24h against the chore's own last 7 days, with today, the median and a multiplier. Rows above 2x get `~`. At 160 wide it adds a 7-day strip (`.:-=+*#` by quantile).
- `w` switches the band between 7 and 28 days. `Enter` on a chore scope opens the Chore screen.

**Wire.** `S.usage` for the table. The band is derived (1.4).

### 6.9 5 Inbox

**Use.** Notifications, unread first. `*` marks unread; `!` or `i` gives the level. Text wraps and is never truncated. `Enter` opens the linked run, or the chore. `d` dismisses one, and `D` dismisses everything shown.

**Wire.** `S.notifications`. `d` calls `A.dismiss(id)`. `D` calls `A.dismiss` once for each unread id shown.

### 6.10 6 System

**Use.**

- **Facts:** scheduler (installed, tick, last tick and its age, ok/STALE), ledger rows, state directory size, pause, and warnings (each prefixed `!!`).
- **Action rows,** chosen with the cursor and `Enter`:

  | Row | Confirms? |
  |---|---|
  | validate | no |
  | install | no |
  | uninstall | yes |
  | prune | yes |
  | pause all | reason prompt |

- These five actions have no global keys, because they are rare and heavy. The one exception is pause all, which `P` also opens from anywhere.

**Wire.** As the app's System view (2.11).

### 6.11 Overlays

Only one overlay is open at a time. Letters go to the overlay, not the screen behind it. Every `[key]` label is also clickable with the mouse.

| Overlay | Opened by | Keys |
|---|---|---|
| Refusal | `r` when refused | `F` force (only if every cause is forceable), `K` kill the running one (overlap), `u` / `U` resume, `t` dry run, `Esc` close |
| Dry-run plan | `t` | `Esc` close |
| Confirm (kill, breaker resume, resume all, uninstall, prune) | the action key | `y` or `Enter` confirm (for kill, `K` again also confirms), `Esc` or `n` cancel |
| Reason prompt (pause chore, pause all) | `p`, `P` | type the reason, `Tab` toggle "also kill running runs" (pause all only), `Enter` confirm (blocked while empty), `Esc` cancel |
| Validate result | System > validate | `Esc` close |
| Help | `?` | `Esc` close |

The content of each overlay matches the app's sheet with the same name (2.12).

### 6.12 Key map

vim keys and arrow keys are aliases for the same actions.

| Key | Alias | Where | Action |
|---|---|---|---|
| `1`..`6` | click tab | anywhere | Needs, Chores, Runs, Usage, Inbox, System |
| `j` / `k` | Down / Up | lists, panes | move |
| `g` / `G` | Home / End | lists, panes | top / bottom |
| `Ctrl-d` / `Ctrl-u` | PgDn / PgUp | lists, panes | half page (PgDn/PgUp: full page) |
| `l` / `Enter` | Right, click the selected row | lists | open |
| `h` / `Esc` | Left, Backspace | anywhere | back; close the overlay; clear the filter |
| `Tab` / `Shift-Tab` | click tab | Run | next / previous artifact tab |
| `/` | | Chores, Run | filter / search |
| `n` / `N` | | Run | next / previous match |
| `c` / `o` | | chore context | open the chore / its last run |
| `r` / `t` | | chore context | run now / dry run |
| `p` / `u` | | chore context | pause / resume the chore |
| `K` | | a running chore or run | kill (confirms) |
| `P` / `U` | | anywhere | pause all / resume all |
| `d` / `D` | | Needs, Inbox | dismiss / dismiss all shown |
| `s` | | Chores | cycle the sort |
| `w` | | Usage; Run panes | trend window; wrap |
| `=` | | Run | Compare tab |
| `z` | | Transcript | expand / collapse all |
| `v` | | Run | open the artifact in `$PAGER` |
| `y` | | Run, Runs | copy the run id (OSC 52) |
| `F2`..`F4` | | Runs | query presets |
| `F` | | Refusal | force |
| `Ctrl-r` | | anywhere | poll now |
| `?` | | anywhere | help |
| `q` | | anywhere | quit |

### 6.13 Monochrome carriers

In the terminal, colour is a reinforcement only. What carries each state without colour:

| State | Carrier |
|---|---|
| level | `!!` `!` `~` `i` in the LV column |
| chore state | the ST glyph (`* B P X -`) |
| run status | the full status word (`BUDGET_EXCEEDED`, never an abbreviation) |
| unread | `*` |
| cursor | `>` in column 1 (and reverse video) |
| active tab | `[ ]` brackets |
| modes | the row-2 banner prefixes `!!` and `||` |
| old data | the `DATA OLD` text |
| action result | the `ok:` / `refused:` / `failed:` / `...` prefix |
| diff | `-` / `+` prefixes |

The colour ramp, when available: alert = accent-400, warn = accent-200, running = accent-300, muted = neutral-500, faint = neutral-700, selection = neutral-800 background.

### 6.14 App <-> TUI parity

Every function exists on both surfaces. Implement the logic once and bind it twice.

| Function | App | TUI |
|---|---|---|
| What needs me | Needs you view | `1` Needs |
| Every chore | All chores (filter field + segments) | `2` Chores (`/` tokens, `s` sort) |
| One chore | Inspector (right pane / slide-over) | Chore screen (`Enter` or `c`) |
| Cross-chore run query | -- (v1.1: a Runs view) | `3` Runs, presets F2-F4 |
| One run | Run view, segmented tabs | Run screen, `Tab` tabs |
| Transcript search | search field | `/`, `n`/`N` |
| Compare definitions | Compare tab, side by side | Compare tab, unified (`=`) |
| Usage vs ceilings | Usage cards | `4` Usage table |
| Against your usual | Usage, bar rows | `4` Usage band (`w`) |
| Notifications | Inbox | `5` Inbox |
| Scheduler and maintenance | System | `6` System |
| Today at a glance | Today timeline | -- (by design: the timeline needs pixels) |
| Run now | button / Cmd-R | `r` |
| Dry run | button / Cmd-Shift-R | `t` |
| Kill | button / Cmd-. | `K` |
| Pause / resume a chore | buttons / Cmd-P, Cmd-U | `p` / `u` |
| Pause / resume all | toolbar / Cmd-Shift-P, Cmd-Shift-U | `P` / `U` |
| Dismiss | button / Cmd-D | `d` / `D` |
| Force | Refusal sheet button | `F` in the refusal overlay |
| Validate, install, uninstall, prune | System rows | System rows |
| Freshness | toolbar pill | row 1 clock, `DATA OLD` |
| Modes | banners | row-2 banner |
| Action feedback | toasts | message line |

---

## 7. CLI

`chores status`, `chores runs`, `chores show <run-id>` print plain text with no colour and no box drawing. It stays legible when piped to a file or `less`. The exact output is mocked in `chores-ux-design.md` section 8.

`chores status` exit codes: 0 when nothing is at alert level or worse, 1 for alerts, 2 for a system problem, 3 if the snapshot failed.

Scripts use `--json`, which is not specified here. `chores show <id> --artifact <name>` prints one artifact raw.

---

## 8. Walkthroughs (how to use)

Each walkthrough gives the steps in the app, then the keystrokes in the TUI.

**"Something needs me."** The menu-bar title shows `!3`, or a notification arrives.
- *App:* click the notification, or open the menu and choose the item. The app opens on that chore or run. Read the reason, then act from the inspector, or open the run for the transcript.
- *TUI:* `chores dash` opens on Needs. Use `j`/`k` to reach the row and `Enter` to open its run.

**"Why did pr-digest stop?"**
- *App:* Needs you -> the pr-digest row -> **Open run**. The budget bar shows 52,300 against 50,000. Transcript -> the last turn shows where it crossed. Compare shows that the budget dropped from 60,000 to 50,000 in an uncommitted edit (`a41c9e2-dirty`).
- *TUI:* Needs -> the pr-digest row -> `Enter` (Run, Transcript tab) -> `G` for the last lines -> `=` for Compare: `- budget: {tokens: 60000}` `+ budget: {tokens: 50000}`.
- Either way, fix it in git.

**"Unstick inbox-triage."**
- *App:* select it. The inspector shows "Paused by breaker" and the failure sequence. Choose **Dry run first**, then **Resume**.
- *TUI:* select the row, press `t` to check the plan, `Esc`, then `u` -> `y`.

**"Stop everything, I'm getting on a plane."**
- *App:* toolbar **Pause all**. Type a reason and, if needed, tick "Also kill what is running now". Afterwards: **Resume all**.
- *TUI:* `P`, type `on a flight`, `Tab` to also kill, `Enter`. Afterwards: `U` -> `y`.
- Every surface shows the pause: the banner, the `||` row, and `PAUSED` in the menu bar. Slots during the pause appear as SKIPPED_PAUSED, one warning per chore, after you resume.

**"Is anything burning money?"**
- *App:* Usage. Check the scope cards for accented meters, then **Against your usual** for anything over 2x (pr-digest, 2.4x).
- *TUI:* `4`. Look for `~` and `!` in the table and `~ 2.4x` in the band. `w` compares against 28 days instead of 7.

**"Run something now."**
- *App:* select the chore, then **Run now** (Cmd-R).
- *TUI:* select the chore, then `r`.
- If it is refused, the sheet or overlay names every cause and offers Force (`F`) only when every cause can be forced.

**"Which runs blew their budget this month?"**
- *TUI:* `3` -> `F3`.
- *App:* v1.1 (the Runs view). Until then, use the TUI or `chores runs`.

**"Read a huge transcript."**
- *App:* search field + turn groups.
- *TUI:* `/` + `n`/`N`, `:880` to jump, or `v` to hand it to `less`.

---

## 9. State catalogue: what the app shows

The TUI appearance of each state is in `chores-ux-design.md`, section 6. The carriers are summarised in 6.13 above.

| State | App appearance |
|---|---|
| Zero chores | Needs you: "Nothing needs you." + "No chores are defined yet. Add a definition in git; it appears here on the next tick." All chores: empty table message. Timeline hidden. |
| Not installed | Banner with Install; freshness pill "Scheduler not installed"; System badge `!`; menu title `OFF`; future ticks hidden |
| Scheduler stale | Banner with Reinstall; pill "Last tick 4h 53m ago"; menu title `STALE`; one macOS notification per episode |
| Global pause | Banner with Resume all; toolbar button "Resume all"; inspector tag "Global pause"; next due "held"; menu title `PAUSED` |
| Paused by breaker | alert row with Resume; inspector tag; lane hatched from the pause |
| Invalid definition | alert row; inspector violation box; Run now refused (not forceable); future ticks dimmed |
| Run in progress | spinning icon; growing bar on the timeline; inspector primary button is Kill; the Run view follows the tail |
| Killed / timed out / over budget / offline / interrupted | the status icon and word everywhere; the reason on the row and in the Run header; INTERRUPTED shows ended as `--`, never a guessed time |
| Missed after sleep | warning row with the count and window; hollow ring on the timeline; sleep hatch where known |
| Battery deferral | warning row "held until AC power"; Run now refusal can be forced |
| Ceiling near / at | accented meter (>= 80%); warning row, becoming an alert row at 100%; menu Usage submenu line ends `~` or `!` |
| Truncated record | warning row; the Run view tabs get the "(truncated)" suffix and a pane notice |
| Ledger shrank | a system alert row with the line verbatim; System warnings; menu `!!1`; a macOS notification |
| Snapshot failed | a banner with the error; the pill "Data from HH:MM:SS"; content kept but dimmed; every action refused with "Status could not be read"; menu `?` |

---

## 10. Implementation checklist

- [ ] One `attention()` implementation shared by the app, the menu-bar item, the TUI and `chores status`
- [ ] One status vocabulary table (1.3) shared by all surfaces
- [ ] The snapshot age shown on every surface; last good snapshot kept when a poll fails
- [ ] Scheduler health shown separately from data age
- [ ] Every run-now refusal lists all causes; Force only when all are forceable
- [ ] Kill, Uninstall, Prune, Pause all and breaker Resume confirm; Run now, Dismiss, Install and operator Resume do not
- [ ] Global pause and chore pause require a reason
- [ ] The menu bar never performs a refusable action in place
- [ ] Deep links (1.7) handled by the app, used by the menu bar, notifications and the Dock
- [ ] Transcript streamed and virtualised; thousands of lines scroll smoothly
- [ ] No secret values anywhere; secret names in the dry run only
- [ ] Every state in section 9 reachable in a test fixture (the prototype's scenario tweak lists them)
- [ ] Monochrome check: each state distinguishable with colour removed (icon shape + word)
- [ ] Narrow window (< 1,220 px) turns the inspector into a slide-over
- [ ] TUI: works at 80x24 over ssh; shows the 80x24 line when smaller; relays out on resize
- [ ] TUI: NO_COLOR run passes the monochrome carrier table (6.13)
- [ ] TUI: every function in the parity table (6.14) is reachable by keyboard alone
- [ ] TUI: transcripts of thousands of lines scroll at key-repeat speed (windowed reads)
- [ ] TUI: overlays capture letters; Esc always backs out one level

---

## 11. Data gaps and open questions

Data gaps. The UI is designed for these to be absent:

- **D-a** Sleep intervals are not recorded. The timeline's sleep band is derived from MISSED reasons when present.
- **D-b** Budget and timeout are not in the chore snapshot. They are shown from the last run's `definition.md`, or in the dry run.
- **D-c** The transcript schema is unknown. Grouping by turn needs a `turn` key.
- **D-d** No per-run record of the secrets used.
- **D-e** No cpu bound, only `cpu_seconds` recorded.

Open questions (the default applies if nobody answers):

- **Q1** Acknowledge a failed run so it leaves Needs you? Default: no; it clears on the next success.
- **Q2** Can Run now start a disabled chore? Default: no, refused and not forceable.
- **Q3** The "running long" threshold? Default: 3x the median of the last 10 successes, and > 60 s.
- **Q4** The near-ceiling threshold? Default: 80%.
- **Q5** The trend flag? Default: > 2x the 7-day median, with at least 7 days of history.
- **Q6** Do info messages raise macOS notifications? Default: no.
- **Q7** Does the transcript have stable `turn` / `type` keys? Default: assume not; render flat and group only when the keys are present.
- **Q8** Does the app window live in the menu-bar process or in a separate app? Default: a separate app bundle, with the menu-bar item as a login item; both poll independently.
