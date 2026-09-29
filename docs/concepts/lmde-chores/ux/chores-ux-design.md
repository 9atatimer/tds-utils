# chores -- UX design

Operator inputs from the interview, applied throughout:

- 40+ chores. Lists are built to filter and rank, not to fit on one screen.
- The operator finds out through the menu bar and macOS notifications, and
  opens the dashboard only when told to. The dashboard lands on "Needs me",
  an attention queue. All chores are one key away.
- Key bindings: vim and arrows both work, as aliases for the same actions.
- Menu-bar title: icon only when quiet. Unread info messages DO change the
  title.
- "Burning budget" means "out of pattern versus earlier days and weeks",
  both in total and per chore. The Usage screen shows a trend band computed
  from run records, alongside the 24h ceilings.
- One committed design. No alternatives.

Conventions in every wireframe: `[x]` marks the active tab or button
(reverse video on screen). `>` in column 1 is the cursor row. Times are
local. Today's times are HH:MM:SS; earlier days are "Fri 08:45"; anything
older than 7 days is "2026-09-14 09:00".

---

## 1. Mental model

The operator thinks in **chores**. A chore is a definition in git that the
dashboard can read but never change. Each time a chore's slot comes due,
it produces a **run record**. A record is either a real run (with
**artifacts**: transcript, errors, stdout, stderr, and the definition
snapshot it ran) or a non-run outcome that explains why nothing ran
(MISSED, SKIPPED_*, DEFERRED_BATTERY, INVALID). Runs are served by a
**backend**. Usage is charged against **scopes** (global, per backend,
per chore), and each scope may have a rolling-24h ceiling. **Notifications**
come from runs or from chores, and point back at them. Over all of this sit
two machine facts: the **scheduler** (is the 60s tick alive?) and the
**global pause** (the kill switch). Every surface renders one **snapshot**
of all this. The snapshot has an age, and every surface shows that age.
The operator never works with "screens". They work with a derived
**attention item**, which is always about exactly one object: the
scheduler, the pause, a chore, a run, a scope, a notification, or a
warning line.

Information architecture:

```
Glance (menu bar)
|  title = worst attention state; dropdown = attention items + running
|  every item -> "Open in Dashboard" deep link (Launcher, focused on it)
|
Launcher (Dock tile) -> opens or focuses the one Dashboard
|
Dashboard (chores dash)
+-- 1 Needs me .......... attention queue, ranked (landing screen)
|     Enter on item -> the item's object (run / chore / scope / System)
+-- 2 Chores ............ every chore, filter + sort, 40+ rows
|     Enter -> Chore
|        +-- header facts, pinned last ok / last failure
|        +-- run history (queried)
|              Enter -> Run
+-- 3 Runs .............. cross-chore run query (window x status x chore)
|     Enter -> Run
|        +-- header facts
|        +-- tabs: Transcript | Errors | Stdout | Stderr | Definition | Compare
+-- 4 Usage ............. scopes x dimensions vs ceilings; trend vs prior days
|     Enter on chore scope -> Chore
+-- 5 Inbox ............. notifications, unread first
|     Enter -> linked run, else linked chore
+-- 6 System ............ scheduler, warnings, state dir, rare actions
|
Overlays (any screen): Confirm | Refusal | Dry-run plan | Reason prompt |
                       Validate result | Help (?)

CLI (chores status | runs | show) -- the same snapshot and queries, as text
```

Moving around: `1`-`6` jump to a top-level screen from anywhere.
`Enter`/`l`/Right goes one level deeper. `Esc`/`h`/Left/Backspace goes one
level back. Each top-level screen remembers its cursor and scroll. Deep
links from the menu bar push the target onto the stack as if you had
walked there, so `Esc` always leads somewhere sensible.

---

## 2. Attention model

Four levels. The glyph carries the meaning. Colour only reinforces it.

- `!!` SYSTEM -- the machine cannot be trusted to run anything correctly.
- `!` ALERT -- something stopped or will not run until the operator acts.
- `~` WARN -- something did not happen, or is heading for a limit. Self-
  clears or is expected.
- `i` INFO -- an unread message.
- `||` PAUSE is a mode, not a level. It is shown as a banner and a title
  word on every surface, because the operator chose it.

Rank inside the queue: level, then the ranks below, then newest first.
A chore with several conditions shows one row per condition. Each row
names the condition, so nothing is merged away.

| # | Condition | Level | Glance (menu bar) | Dashboard | Launcher | CLI `status` | Clears by |
|---|---|---|---|---|---|---|---|
| 1 | Snapshot failed to load | `!!` | title `?`; menu line 1 = error text | banner row 2 "SNAPSHOT FAILED", last good data kept, dimmed, with its age | splash shows error, then dashboard in failed mode | exit 3, error on stderr | self-clears on next good snapshot |
| 2 | Scheduler not installed | `!!` | title `OFF` | banner "SCHEDULER NOT INSTALLED -- nothing fires" + queue row | same as dashboard | `scheduler  NOT INSTALLED` first line | act: System > install |
| 3 | Scheduler stale (3+ intervals) | `!!` | title `STALE` | banner "SCHEDULER STALE -- last tick 09:12:04 (4h53m)" + queue row | same | `scheduler  STALE` | self-clears on next tick; act: install again |
| 4 | Warning/problem line (ledger shrank, interval mismatch, unreadable state) | `!!` | title `!!n`; menu lists line text | queue row per line, text verbatim; System screen | same | `WARNINGS` block | self-clears when the snapshot stops reporting it |
| 5 | Chore paused by breaker | `!` | title `!n`; menu item | queue row; Chores ST glyph `B` | same | `ALERT` row; state `PAUSED(breaker)` | act: resume (`u`) |
| 6 | Ceiling at exhaustion (any scope, any dimension, >= 100%) | `!` | title `!n`; Usage submenu line | queue row; Usage row `! AT CEILING` | same | `ALERT` row; usage row `AT CEILING` | self-clears as the 24h window rolls |
| 7 | Last run FAILED / TIMED_OUT / BUDGET_EXCEEDED / INTERRUPTED | `!` | title `!n`; menu item | queue row with status + reason | same | `ALERT` row | self-clears on the chore's next SUCCEEDED run |
| 8 | Definition INVALID | `!` | title `!n`; menu item | queue row; Chores ST glyph `X` | same | `ALERT` row | self-clears when git fixes the definition |
| 9 | Unread alert notification | folds into its chore's `!` row (marked "unread"); standalone `!` row if no chore | counted once with its chore | row shows `* unread n-0412` | same | `ALERT` row lists it | acknowledge: dismiss (`d`) |
| 10 | Run RUNNING well past normal | `~` | title `~n`; Running section shows "(usual 41s)" | queue row "RUNNING 5m10s; usual 41s" | same | `WARN` row | self-clears when the run ends; act: kill (`K`) |
| 11 | Ceiling near (>= 80%) | `~` | Usage submenu line ends `~` | queue row; Usage `~ NEAR` | same | `WARN` row | self-clears |
| 12 | Last run KILLED | `~` | counted in `~n` | queue row | same | `WARN` row | self-clears on next SUCCEEDED |
| 13 | Last run OFFLINE | `~` | counted in `~n` | queue row "OFFLINE -- no network, not a fault" | same | `WARN` row | self-clears on next SUCCEEDED |
| 14 | Slots MISSED / SKIPPED_* / DEFERRED_BATTERY | `~` | counted in `~n` | queue row with count and reason | same | `WARN` row | self-clears on next run of that chore; DEFERRED clears on AC |
| 15 | Run record truncated | `~` | counted in `~n` | queue row "TRUNCATED -- artifacts incomplete" | same | `WARN` row | self-clears when a newer run of the chore is not truncated |
| 16 | Unread info notification | `i` | title `n` (count only) when nothing worse | queue row with message text | same | `INFO` row | acknowledge: dismiss (`d`) |
| -- | Global pause on | mode `||` | title `PAUSED`, prefixed to any count | banner row 2, inverted | same | `pause  ON "on a flight"` | act: resume all (`U`) |

Notes:

- KILLED and OFFLINE are `~`, not `!`. The operator caused one, and the
  network caused the other. That is the "on a flight" story.
- "Well past normal" = elapsed > 3x the median wall time of the chore's
  last 10 SUCCEEDED runs, and > 60 s. This is computed from the run query.
  In the sample, log-brand-sweep has run 5m10s against a last success of
  41s.
- There is no "acknowledge" for a failed run. The domain has no field for
  it. A failed run stays in the queue until the chore runs clean. Dismissing
  the matching alert notification removes the "unread" marker. That is the
  only acknowledgement that exists (see Open questions).
- Launcher surfaces nothing on its own: no Dock badge (see Rejected
  alternatives). Its "surface" column means what the dashboard shows once
  it opens.

---

## 3. Glance (menu bar)

Polls the snapshot every 15 s, and once more immediately when the menu
opens. If the menu-bar item's own snapshot is older than 60 s, the title
gets the `?` suffix.

### Title per state

| State | Title (text) | What the real icon depicts |
|---|---|---|
| All quiet (running counts as quiet) | `[c]` | outline checklist: three short lines with ticks |
| Info only (n unread) | `[c] 1` | same icon |
| Warn only | `[c] ~5` | same icon |
| Alert | `[c] !3` | checklist with a solid exclamation badge bottom-right |
| System problem line | `[c] !!1` | same badge icon |
| Global pause | `[c] PAUSED` | two vertical pause bars instead of the checklist |
| Pause + alerts | `[c] PAUSED !3` | pause bars |
| Scheduler stale | `[c] STALE` | checklist with a clock face overlaid |
| Not installed | `[c] OFF` | checklist struck through with one diagonal |
| Snapshot failed or menu data > 60 s old | `[c] ?` | checklist drawn in outline only (hollow) |

Precedence: `?` > `OFF` > `STALE` > `PAUSED`. Then the worst count is
appended: `!!n` > `!n` > `~n` > `n`. Only one count is shown. The number
counts items at that level. The template icon adapts to light and dark
menu bars. The icon is never tinted, so the state is always in the glyph
and the word.

Menu rules: the menu never performs an action that can be refused or needs
confirmation. Those open the dashboard focused on the object. Exactly two
actions run in place: Dismiss (per message, and "Mark all read") and Resume
All. Resume All is safe and one-way; the operator set the pause, and
releasing it is the point of the item.

### Dropdown: all quiet

```
All quiet                                (disabled header)
Snapshot 14:05:12  -  last tick 14:04:31 (disabled)
-----------------------------------------
Running
    log-brand-sweep   since 14:00:02  >  Open in Dashboard
                                         Kill in Dashboard...
Next up
    log-brand-sweep   14:30           (disabled)
    workspace-gc      Sun 03:00       (disabled)
    daily-local-smoke Sun 04:00       (disabled)
-----------------------------------------
Usage 24h                              >  global tokens 182,400 / 500,000 (36%)
                                          global turns 41 / 200 (21%)
                                          gateway usd 1.84 / 3.00 (61%)
                                          gateway tokens 40,300 / 100,000 (40%)
                                          agent-cli turns 41 / 150 (27%)
                                          pr-digest tokens 52,300 / 60,000 (87%) ~
                                          pr-digest turns 18 / 20 (90%) ~
-----------------------------------------
Open Dashboard                     Cmd-D
Pause All...                          (opens dashboard reason prompt)
-----------------------------------------
Quit chores Menu                   Cmd-Q
```

("All quiet" for the menu means no `!!`, `!` or `~` items and no unread
messages. The usage lines above are the sample's. In a truly quiet state,
none of them would end in `~`.)

### Dropdown: something failed (the sample snapshot)

Title: `[c] !3`

```
3 need you  -  5 warnings  -  1 message  (disabled header)
Snapshot 14:05:12  -  last tick 14:04:31 (disabled)
-----------------------------------------
! inbox-triage      paused by breaker  >  3 consecutive failures (disabled)
                                          Last run TIMED_OUT 12:00:00 (disabled)
                                          -----
                                          Open in Dashboard
                                          Resume in Dashboard...
                                          Dismiss alert n-0412
! pr-digest         BUDGET_EXCEEDED    >  tokens 52,300 > budget 50,000 (disabled)
                                          -----
                                          Open Run in Dashboard
                                          Dismiss alert n-0409
! notes-summarize   INVALID            >  budget lacks usd; backend gateway
                                          has a usd ceiling (disabled)
                                          -----
                                          Open in Dashboard
~ 5 warnings                           >  log-brand-sweep  running 5m10s, usual 41s
                                          pr-digest  ceiling near (turns 90%)
                                          release-notes-draft  SKIPPED_CEILING 13:00
                                          workspace-gc  MISSED x2 (asleep)
                                          weekly-gateway-smoke  OFFLINE Mon
                                          (each opens the item in Dashboard)
i pr-digest: 3 PRs need your review    >  08:51:57 (disabled)
                                          Open in Dashboard
                                          Dismiss
-----------------------------------------
Running
    log-brand-sweep   5m10s (usual 41s)  >  Open in Dashboard
                                            Kill in Dashboard...
-----------------------------------------
Usage 24h                              >  (as in "all quiet")
-----------------------------------------
Open Dashboard                     Cmd-D
Mark All Messages Read
Pause All...
-----------------------------------------
Quit chores Menu                   Cmd-Q
```

The 3 alerts (n-0412, n-0409) also raised macOS notifications when they
were posted. Clicking one opens the dashboard at the item. Info messages
(n-0408) post no system notification. They change only the title.

### Dropdown: global pause active

Title: `[c] PAUSED !3`

```
PAUSED: "on a flight"  since 06:40      (disabled header)
Nothing starts until you resume.        (disabled)
-----------------------------------------
Resume All                              (runs in place; no confirm)
-----------------------------------------
3 need you  -  5 warnings  -  1 message  (disabled)
! inbox-triage      paused by breaker  >  ...as above
! pr-digest         BUDGET_EXCEEDED    >  ...
! notes-summarize   INVALID            >  ...
~ 5 warnings                           >  ...
i pr-digest: 3 PRs need your review    >  ...
-----------------------------------------
Open Dashboard                     Cmd-D
-----------------------------------------
Quit chores Menu                   Cmd-Q
```

"Pause All..." is replaced by "Resume All". During the pause, slots write
SKIPPED_PAUSED records. They show up as `~` rows only after resume, so the
queue is not flooded while the pause is known to be on.

### Dropdown: scheduler stale / not installed

Title: `[c] STALE`

```
Scheduler STALE                         (disabled header)
Last tick 09:12:04 -- 4h53m ago.        (disabled)
Nothing has fired since then.           (disabled)
Fix: chores install                     (disabled)
-----------------------------------------
Open System in Dashboard
-----------------------------------------
3 need you  -  5 warnings  -  1 message  >  ...(same items)
-----------------------------------------
Open Dashboard                     Cmd-D
-----------------------------------------
Quit chores Menu                   Cmd-Q
```

Title: `[c] OFF` -- the same, with the header "Scheduler NOT INSTALLED",
the line "Nothing fires on schedule.", and the same fix line. "Open System
in Dashboard" lands on the install action row.

Snapshot failed, title `[c] ?`:

```
Status unavailable                      (disabled header)
<error text from the snapshot call>     (disabled)
Last good snapshot 14:05:12 (3m ago)    (disabled)
-----------------------------------------
Open Dashboard                     Cmd-D
Quit chores Menu                   Cmd-Q
```

Items from a stale menu snapshot are never listed as current.

---

## 4. Dashboard

Frame, every screen, at any size:

```
row 1       tabs + snapshot clock        (always)
row 2       context line: summary, or a MODE BANNER (pause / scheduler /
            snapshot failure) in reverse video
rows 3..H-2 content
row H-1     message line: result of the last action, or blank
row H       key hints for the focused pane (the most useful 6-8 only; ? for all)
```

Freshness: the dashboard polls the snapshot every 2 s. Detail queries (run
history, artifacts) re-query on every poll only while their screen is
visible. Row 1 ends with the snapshot's `at` time and its age: `14:05:12
+2s`. Once the age exceeds 3 polls (6 s), that cell turns into `DATA OLD
+47s` in reverse video, and all content dims one step. Content that is
stale is never shown as current. The scheduler's own freshness is a
separate fact on row 2 (`tick 14:04:31 ok`), so "my view is old" and "the
machine stopped ticking" never look the same. `Ctrl-r` forces a poll.

At 160x48, every list gains columns and a detail pane on the right. Nothing
moves.

### 4.1 Needs me (landing)

Purpose: one ranked list of everything that needs the operator, each row
one step from its object.

80x24, sample:

```
chores [1 Needs !3] 2 Chores 3 Runs 4 Usage 5 Inbox 3 6 System   14:05:12 +2s
3 alert  5 warn  1 info   -   tick 14:04:31 ok   -   no pause
 LV CHORE                WHAT                                          SINCE
>!  inbox-triage         PAUSED by breaker: 3 consecutive failures     12:00
 !  pr-digest            BUDGET_EXCEEDED tokens 52,300 > budget 50,000 08:45
 !  notes-summarize      INVALID budget lacks usd; gateway has usd ceil 14:04
 ~  log-brand-sweep      RUNNING 5m10s; usual 41s                       14:00
 ~  pr-digest            ceiling near: turns 18/20 90%, tokens 87%      now
 ~  release-notes-draft  SKIPPED_CEILING usd 1.84+1.50 > gateway 3.00   13:00
 ~  workspace-gc         MISSED x2 while asleep 01:10-07:55, no catch_up 03:00
 ~  weekly-gateway-smoke OFFLINE backend gateway unreachable            Mon
 i  pr-digest            "3 PRs need your review"                      08:51
-- inbox-triage -------------------------------------- agent / agent-cli ----
 state     PAUSED by breaker: "3 consecutive failures"
           TIMED_OUT, TIMED_OUT, FAILED           * unread alert n-0412
 last run  TIMED_OUT   12:00:00   600s   7 turns
 last ok   08:00:00                        next due  -- (paused)
 schedule  0 * * * *



Enter open last run  u resume  c chore  t dry run  d dismiss  ? keys
```

160x48, sample (right pane = the selected item's object, live):

```
chores  [1 Needs !3]  2 Chores 9  3 Runs  4 Usage  5 Inbox 3  6 System                                                              snapshot 14:05:12  +2s
3 alert  5 warn  1 info   -   scheduler installed, tick 60s, last tick 14:04:31 ok   -   global pause: none   -   warnings: none
 LV CHORE                 WHAT                                                          SINCE    | inbox-triage                         agent / agent-cli
>!  inbox-triage          PAUSED by breaker: 3 consecutive failures                     12:00:01 | ------------------------------------------------------------
 !  pr-digest             BUDGET_EXCEEDED  tokens 52,300 > budget 50,000                08:52:09 | state      PAUSED by breaker: "3 consecutive failures"
 !  notes-summarize       INVALID  budget lacks usd; backend gateway has a usd ceiling  14:04:31 |            TIMED_OUT, TIMED_OUT, FAILED
 ~  log-brand-sweep       RUNNING 5m10s; usual 41s (last success 13:30:01)              14:00:02 | schedule   0 * * * *        next due  -- (paused)
 ~  pr-digest             ceiling near: turns 18 / 20 (90%), tokens 52,300 / 60,000 87% now      | last run   TIMED_OUT   12:00:00   600s   7 turns
 ~  release-notes-draft   SKIPPED_CEILING  usd 1.84 + 1.50 would cross gateway 3.00     13:00:01 | last ok    SUCCEEDED   08:00:00
 ~  workspace-gc          MISSED x2  asleep 01:10-07:55, catch_up off                   03:00    | last fail  TIMED_OUT   12:00:00
 ~  weekly-gateway-smoke  OFFLINE  backend gateway unreachable -- no network, not a fault Mon 09:00 |
 i  pr-digest             "3 PRs need your review"  (posted by the chore)               08:51:57 | notifications
                                                                                                 |  * n-0412 12:00:01 alert  paused by breaker after 3
                                                                                                 |                           consecutive failures (TIMED_OUT,
                                                                                                 |                           TIMED_OUT, FAILED)
                                                                                                 |
                                                                                                 | runs (newest first)
                                                                                                 |    12:00:00  TIMED_OUT   600s   7 turns
                                                                                                 |    ...       (from run query; not in sample)
                                                                                                 |    08:00:00  SUCCEEDED
                                                                                                 |
                                                                                                 | actions
                                                                                                 |    u  resume (clears breaker pause)
                                                                                                 |    t  dry run
                                                                                                 |    o  open last run (TIMED_OUT 12:00:00)
                                                                                                 |    d  dismiss n-0412
  (38 rows of queue space)                                                                       |

Enter open last run   u resume   c chore   t dry run   d dismiss   / filter   Ctrl-r refresh   ? keys   q quit
```

Keys: `j`/`k`/Up/Down move; `g`/`G`/Home/End top/bottom; `Enter`/`l`
opens the item's object (run-status rows open the run on the Transcript
tab; INVALID opens the chore with its violations; ceiling rows open Usage
at that scope; `!!` rows open System; info rows open the linked run, else
the chore). `c` opens the chore. `o` opens its last run. `r` run now. `t`
dry run. `u` resume (chore). `K` kill (running rows). `d` dismiss the
row's notification. `/` filter. `?` keys.

Empty queue: row 3 shows `Nothing needs you.` Then one line: `9 chores -
1 running (log-brand-sweep since 14:00:02) - next: log-brand-sweep 14:30`.
Nothing else.

Refresh: follows the snapshot. When a row disappears because its condition
cleared, the cursor stays at the same index. The message line says
`cleared: pr-digest ceiling near` for 5 s, so rows never vanish unexplained.

### 4.2 Chores

Purpose: every chore, with state, last outcome and next slot. Scales to
40+ through filter and sort.

80x24, sample (sort: attention, then name):

```
chores 1 Needs !3 [2 Chores 9] 3 Runs 4 Usage 5 Inbox 3 6 System 14:05:12 +2s
9 chores  1 running  1 paused  1 invalid  1 disabled     sort: attention
 ST NAME                  KIND/BACKEND     LAST                       NEXT
>B  inbox-triage          agent/agent-cli  TIMED_OUT       12:00:00   paused
 X  notes-summarize       prompt/gateway   INVALID         14:04:31   --
    pr-digest             agent/agent-cli  BUDGET_EXCEEDED 08:45:00   Sun 08:45
 *  log-brand-sweep       command          RUNNING         14:00:02   14:30
    release-notes-draft   prompt/gateway   SKIPPED_CEILING 13:00:01   Mon 13:00
    workspace-gc          command          MISSED x2       03:00      Sun 03:00
    weekly-gateway-smoke  prompt/gateway   OFFLINE         Mon 09:00  Mon 09:00
    daily-local-smoke     prompt/local     SUCCEEDED       04:00:03   Sun 04:00
 -  repo-cleanup          command          SUCCEEDED   2026-08-30     disabled

ST:  * running   B paused by breaker   P paused by you   X invalid
     - disabled in git   (blank) enabled







Enter chore  o last run  r run now  t dry run  p pause  / filter  s sort  ?
```

ST glyphs are the monochrome carrier. Colour adds accent to `B`/`X`, the
accent ramp to `*`, and dim to `-` rows. The legend rows appear only while
the list is shorter than the screen.

160x48 adds: `LAST OK`, `LAST FAIL`, `24h TOKENS`, `24h USD`, `SCHEDULE`,
and the reason text for the last run. The right pane shows the selected
chore (as 4.3, header only).

Filter (`/`): free text matches name and description. Tokens narrow
further: `state:paused|invalid|disabled|running`, `kind:agent`,
`backend:gateway`, `last:FAILED,TIMED_OUT`. The query shows on row 2:
`filter: backend:gateway  (3 of 9)`. `Esc` clears it.

Sort (`s` cycles): attention (default) -> name -> next due -> last run
time.

Disabled chores sort to the bottom under every sort except name. Enabled
chores are never mistaken for disabled: the `-` glyph, the word `disabled`
in NEXT, and the dimming all agree.

### 4.3 Chore

Purpose: one chore's facts, its last good and last bad run pinned, and
its run history.

80x24, pr-digest:

```
chores 1 Needs !3 [2 Chores 9] 3 Runs 4 Usage 5 Inbox 3 6 System 14:05:12 +2s
Chores > pr-digest
 pr-digest                            agent / agent-cli / backend default model
 state     enabled                    schedule  45 8 * * *   next  Sun 08:45
 limits    budget tokens 50,000       (from last run's definition, a41c9e2-dirty)
 24h       tokens 52,300 / 60,000 87% ~   turns 18 / 20 90% ~
 last ok   SUCCEEDED        Fri 08:45
 last bad  BUDGET_EXCEEDED  08:45:00  tokens 52,300 > budget 50,000
 --------------------------------------------------------------------------
   STARTED    STATUS           WALL   TOKENS  TURNS  REV
>  08:45:00   BUDGET_EXCEEDED  429s   52,300     18  a41c9e2-dirty
   Fri 08:45  SUCCEEDED        (older rows: run query; not in sample)
   ...





filter: all statuses, 30 days                                  2 runs
Enter open run  r run now  t dry run  p pause  = compare  / filter  Esc back
```

Pinned `last ok` / `last bad` come straight from the snapshot, so they never
need scrolling. `Enter` on either pinned line opens that run. "limits" is
read from the latest run's definition snapshot, because the chore snapshot
does not carry budget or timeout. It is labelled with that run's rev, and
`t` dry run shows the current resolved values. History filter (`/`):
`status:` set, time window (`7d`, `30d`, `since:2026-09-01`). 160x48 adds
columns `TOK IN`, `TOK OUT`, `USD`, `CPU`, `DISK`, `BACKEND`, `MODEL`,
`REASON` and a 24h sum row (tokens, usd, turns, cpu, disk) computed from
the listed runs.

Invalid chore (notes-summarize): `state INVALID` and every violation, one
per line, in place of the limits line:

```
 state     INVALID -- will not run until fixed in git
             - budget lacks usd; backend gateway has a usd ceiling
```

### 4.4 Runs

Purpose: a cross-chore run query (window x status set x chore), newest
first. This is the reviewer's "what blew up this month".

80x24, sample (window: 24h, all statuses):

```
chores 1 Needs !3 2 Chores 9 [3 Runs] 4 Usage 5 Inbox 3 6 System 14:05:12 +2s
window 24h  status all  chore all                        9 runs   / to change
   STARTED    CHORE                 STATUS            WALL  TOKENS  TURNS
>  14:04:31   notes-summarize       INVALID              -       -      -
   14:00:02   log-brand-sweep       RUNNING          5m10s       -      -
   13:30:01   log-brand-sweep       SUCCEEDED          41s       -      -
   13:00:01   release-notes-draft   SKIPPED_CEILING      -       -      -
   12:00:00   inbox-triage          TIMED_OUT         600s       -      7
   08:45:00   pr-digest             BUDGET_EXCEEDED   429s  52,300     18
   08:00:00   inbox-triage          SUCCEEDED            -       -      -
   07:55      workspace-gc          MISSED x2            -       -      -
   04:00:03   daily-local-smoke     SUCCEEDED         1.9s     212      -







presets: F2 failures 30d   F3 budget+timeout 30d   F4 non-runs 24h
Enter open run  / query  c chore  y yank run id  Esc clear query  ? keys
```

(`-` = not in the sample for that row, or not applicable, e.g. tokens on a
command. 160x48 adds `USD`, `CPU`, `DISK`, `BACKEND/MODEL`, `REV`,
`REASON`.)

Query syntax on `/`: `30d status:FAILED,TIMED_OUT,BUDGET_EXCEEDED
chore:pr-digest`. Presets on F2-F4 are the three questions the stories ask
most. The ledger is never pruned, so month queries work after prune.
Rows whose run directory was pruned show `(pruned)` in REV and open with
header facts only.

### 4.5 Run

Purpose: read one run -- facts, then each artifact as its own thing. See
section 7 for the full treatment and the 80x24 / 160x48 wireframes.

### 4.6 Usage

Purpose: "is anything burning budget?" -- every scope against its ceiling
now, and against its own recent days.

80x24, sample:

```
chores 1 Needs !3 2 Chores 9 3 Runs [4 Usage] 5 Inbox 3 6 System 14:05:12 +2s
rolling 24h to 14:05:12              near >= 80%   ~ near   ! at ceiling
 SCOPE           TOKENS                    USD                TURNS
 global          182,400/500,000  36%      1.84/--            41/200     21%
 local           96,100/--                 --  (unpriced)     --
 gateway          40,300/100,000  40%      1.84/3.00  61%     --
 agent-cli        46,000/--                -- (subscription)  41/150     27%
>pr-digest     ~  52,300/60,000   87%      --                 18/20    ~ 90%
 --------------------------------------------------------------------------
 vs own last 7 days (from run records)          today   7d median   x
 global tokens                                 182,400   (n/a)      -
 pr-digest tokens                               52,300   (n/a)      -
 gateway usd                                      1.84   (n/a)      -
 (sample has no prior-day records; shown values fill in from the run query)

 "--" = no ceiling set, or not billed in that dimension (subscription
 usage counts toward tokens and turns, never usd)


Enter chore/backend  w window 24h|7d|28d  t dry run (selected chore)  ? keys
```

Trend band (the interview's "out of bounds versus earlier days/weeks"):
for global, each backend and each chore, the dashboard sums the last 24h
of usage per dimension from the run query and compares it with the median
of the same 24h window on each of the previous 7 days (`w` switches to 28
days). Rows at > 2x their median are flagged `~ 2.3x`, sort to the top of
the band, and feed the Needs queue as `~` rows ("pr-digest tokens 2.3x its
7-day median"). This is computed from run records only, as the constraints
require, and it is pure presentation: it never gates admission. At 160x48,
the band lists every chore with non-zero 24h usage (not only chores with a
ceiling), with columns tokens, usd, turns, cpu, disk, and a 7-cell ASCII
day strip per row (`.:-=+*#` by quantile) showing the last 7 days.

### 4.7 Inbox

Purpose: every notification, unread first, each linked to its run or chore.

```
chores 1 Needs !3 2 Chores 9 3 Runs 4 Usage [5 Inbox 3] 6 System 14:05:12 +2s
3 unread  1 read
 U LV  AT         CHORE                 TEXT
>* !   12:00:01   inbox-triage          paused by breaker after 3 consecutive
                                        failures (TIMED_OUT, TIMED_OUT, FAILED)
 * !   08:52:10   pr-digest             BUDGET_EXCEEDED: tokens 52,300 > budget
                                        50,000
 * i   08:51:57   pr-digest             3 PRs need your review  (from chore)
   i   Mon 09:00  weekly-gateway-smoke  OFFLINE: backend gateway unreachable













Enter open linked  d dismiss  D dismiss all shown  c chore  / filter  ?
```

`*` = unread (the carrier). Read rows are dimmed and lose the `*`. Text
wraps and is never truncated.

### 4.8 System

Purpose: the machine's health and the rare, heavy actions.

```
chores 1 Needs !3 2 Chores 9 3 Runs 4 Usage 5 Inbox 3 [6 System] 14:05:12 +2s
System
 scheduler   installed   tick 60s   last tick 14:04:31 (41s ago)   ok
 ledger      4,210 rows
 state dir   (size: queried on open; not in sample)
 pause       none
 warnings    none
 --------------------------------------------------------------------------
 actions
>  validate      check every definition, list every violation
   install       put the 60s tick into the OS scheduler (re-run to repair)
   uninstall     remove the tick -- nothing fires until install
   prune         delete run directories older than the retention window
   pause all     same as P from anywhere









Enter run action  ? keys
```

Warnings appear verbatim, one per line, prefixed `!!`. The action rows are
the only place these five actions live. They have no global keys, because
they are rare and heavy.

### 4.9 Key map

| Key | Alias | Where | Action |
|---|---|---|---|
| `1`..`6` | click tab | anywhere | Needs, Chores, Runs, Usage, Inbox, System |
| `j` / `k` | Down / Up | lists, panes | move cursor / scroll one line |
| `g` / `G` | Home / End | lists, panes | top / bottom |
| `Ctrl-d` / `Ctrl-u` | PgDn / PgUp | lists, panes | half page (PgDn/PgUp: full page) |
| `l` / `Enter` | Right, double-click | lists | open selected object |
| `h` / `Esc` | Left, Backspace | anywhere | back one level; close overlay; clear filter |
| `Tab` / `Shift-Tab` | click tab | Run | next / previous artifact tab |
| `/` | | lists, panes | filter (lists), search (panes) |
| `n` / `N` | | panes | next / previous search match |
| `c` | | item with a chore | open the chore |
| `o` | | item with a chore | open the chore's last run |
| `r` | | chore context | run now |
| `t` | | chore context | dry run (plan, executes nothing) |
| `p` | | chore context | pause this chore (asks for a reason) |
| `u` | | paused chore | resume this chore |
| `K` | | running run | kill (asks to confirm) |
| `P` | | anywhere | pause all (asks for a reason) |
| `U` | | anywhere, while paused | resume all (asks to confirm) |
| `d` | | notification or item with one | dismiss |
| `D` | | Inbox | dismiss all shown |
| `s` | | Chores | cycle sort |
| `w` | | Usage | cycle trend window 7d / 28d |
| `=` | | Run, Chore | compare definition with another run |
| `Enter` | | Transcript | expand / collapse JSON line |
| `z` | | Transcript | expand all / collapse all |
| `v` | | Run artifact | open this artifact in `$PAGER` |
| `y` | | run context | copy run id (OSC 52; works over ssh) |
| `F2`..`F4` | | Runs | query presets |
| `F` | | Refusal overlay | force (only when every cause is forceable) |
| `y` / `n` | Enter / Esc | Confirm overlay | confirm / cancel |
| `Ctrl-r` | | anywhere | poll the snapshot now |
| `?` | | anywhere | key help overlay |
| `q` | | anywhere | quit dashboard (no confirm; nothing is lost) |

Mouse: clicking tabs, rows and overlay buttons, and the scroll wheel, all
map to the keys above. Nothing is mouse-only.

---

## 5. Actions

Every action reports on the message line (row H-1), prefixed `ok:`,
`refused:`, `failed:` or `...` (in flight). The prefix is the monochrome
carrier. The same text is written to the Inbox only if the system posts a
notification. The dashboard never writes notifications itself.

### Run now -- `r` on any chore context (Needs, Chores, Chore, Run)

- Confirm: none when admission would accept. Running now is what `r` means,
  and a refusal is shown before anything happens.
- Flow: `r` -> `... admitting pr-digest` -> admitted: `ok: started
  daily-local-smoke-20260926T210512Z-<suffix> (PENDING)`. The chore row
  gets `*`. The run appears at the top of Chore and Runs. Its terminal
  status arrives with a later poll, and the Needs queue reacts as usual.
- Refused: a Refusal overlay (it does not auto-dismiss) lists every cause.
  Force is offered only when all causes are forceable:

```
+-- Run now refused: pr-digest ----------------------------------------+
|                                                                      |
|  ceiling   chore pr-digest tokens: 52,300 used + 50,000 budget       |
|            would cross 60,000                         cannot force   |
|                                                                      |
|  Ceilings are never forced. Tokens return as runs age out of the     |
|  24h window.                                                         |
|                                                                      |
|  [t] dry run    [Esc] close                                          |
+----------------------------------------------------------------------+
```

```
+-- Run now refused: log-brand-sweep ----------------------------------+
|                                                                      |
|  overlap   previous run still RUNNING since 14:00:02  (5m10s)        |
|                                                     can force [F]   |
|                                                                      |
|  Forcing starts a second, concurrent run.                            |
|                                                                      |
|  [F] force run    [K] kill the running one    [Esc] cancel           |
+----------------------------------------------------------------------+
```

| Cause | Forceable | Overlay line | Offered next step |
|---|---|---|---|
| global pause | no | `global pause "on a flight" since 06:40` | `U` resume all |
| breaker pause | no | `paused by breaker: 3 consecutive failures` | `u` resume |
| operator pause | no | `paused by you: "<reason>"` | `u` resume |
| ceiling | no | scope, dimension, used + budget > ceiling | `t` dry run |
| invalid | no | every violation | `c` chore |
| overlap | yes | running since, elapsed | `F`, `K` |
| battery | yes | `on battery; defer_on_battery` | `F` |
| offline | yes | `backend <name> unreachable` | `F` (will likely end OFFLINE) |

If there are several causes, for example battery + ceiling, all of them are
listed, force is hidden, and the overlay says `cannot force: ceiling`.

### Dry run -- `t` on any chore context

- Always allowed, no confirm. Executes nothing.
- In flight: `... resolving plan`. Result: the Plan overlay (scrollable,
  `Esc` closes). Values not in the sample are shown as the plan would
  return them:

```
+-- Dry run: pr-digest -- nothing was executed ------------------------+
|  backend   agent-cli (subscription)   model  backend default         |
|  cwd       <from plan>                                               |
|  env       <names only>               secrets <names only; values    |
|                                               never shown>          |
|  budget    tokens 50,000                                             |
|  ceilings  chore pr-digest  tokens 52,300/60,000  turns 18/20        |
|            backend agent-cli turns 41/150                            |
|            global  tokens 182,400/500,000  turns 41/200              |
|  verdict   REFUSE -- SKIPPED_CEILING: tokens 52,300 + 50,000 >       |
|            60,000 (chore pr-digest is the binding ceiling)           |
|                                                          [Esc] close |
+----------------------------------------------------------------------+
```

The verdict line names the binding (smallest-remaining) ceiling, which
answers "the smaller one wins".

### Pause (global) -- `P` anywhere; menu "Pause All..." opens this

- Confirm: yes, as a reason prompt. The reason is required, and pausing
  everything should be deliberate:

```
+-- Pause everything --------------------------------------------------+
|  Nothing will start, by schedule or by hand, until you resume.       |
|  reason: on a flight_                                                |
|  running now: log-brand-sweep (5m10s)                                |
|  [Tab] also kill running runs: off                                   |
|  [Enter] pause    [Esc] cancel                                       |
+----------------------------------------------------------------------+
```

- `Tab` toggles killing the running runs (letters go to the reason) (the two actions are sent in
  order), so the kill switch can mean "stop everything".
- Success: `ok: paused "on a flight"`. Banner row 2 turns into the pause
  banner. The menu-bar title changes on its next poll.
- Refused: none is possible. If a pause is already on, `P` shows it:
  `already paused "on a flight" since 06:40 -- U to resume`.

### Pause (chore) -- `p` on a chore context

- Reason prompt, same shape as above, without the kill toggle, plus a line
  `running now: <id>` if one is running (that run continues; `K` to kill).
- Success: `ok: paused pr-digest ("<reason>")`, and the ST glyph shows `P`.

### Resume -- `u` (chore), `U` (global); menu "Resume All"

- Chore paused by the operator: no confirm.
- Breaker pause: confirm `y`, because the system judged this chore broken:

```
+-- Resume inbox-triage? ----------------------------------------------+
|  Paused by breaker: 3 consecutive failures (TIMED_OUT, TIMED_OUT,    |
|  FAILED). Next slot 15:00 will be admitted.                          |
|  [y] resume    [t] dry run first    [Esc] cancel                     |
+----------------------------------------------------------------------+
```

- Global: confirm `y`, listing the next 3 due slots. The menu's "Resume
  All" skips the confirm, since the menu is the phone-glance path and the
  pause was the operator's own choice.
- Refused: `refused: pr-digest is not paused` (message line only).

### Kill -- `K` on a running run (Needs row, Chores `*` row, Chore, Run)

- Confirm: yes, pressing `K` again or `y`. It is irreversible and throws
  away work:
  `Kill log-brand-sweep? running 5m10s; ends KILLED. [K/y] kill [Esc] cancel`
- In flight: the row reads `RUNNING  kill sent 2s`, until a poll shows
  `KILLED`. Then: `ok: log-brand-sweep ended KILLED`.
- Refused: `refused: run already ended SUCCEEDED at 14:05:20` -- nothing
  to kill.

### Dismiss -- `d` on a notification or on a queue row that carries one; `D` in Inbox

- No confirm. It is low stakes, and the notification stays readable in
  the Inbox.
- Success: the `*` goes, the row dims, and the Needs queue drops the
  `unread` marker (or the `i` row). The title count updates on the menu
  bar's next poll.
- Refused: `refused: n-0391 already read`.

### Prune -- System > prune

- Confirm, stating what is kept:
  `Delete run directories older than the retention window? The ledger and
  notifications are kept; artifacts of those runs are gone. [y] prune [Esc]`
- In flight: `... pruning`. Success: `ok: pruned; state dir <before> ->
  <after>` (the dashboard queries the size before and after). Pruned runs
  still list in Runs, marked `(pruned)`.
- Refused/failed: `failed: <error>`.

### Validate -- System > validate

- No confirm. In flight: `... validating 9 definitions`. Result overlay:
  `1 invalid of 9` and then, per chore, each violation on its own line, for
  example `notes-summarize: budget lacks usd; backend gateway has a usd
  ceiling`. Clean: `ok: all 9 definitions valid`.

### Install / uninstall -- System > install | uninstall

- Install: no confirm, because it is idempotent and repairs interval
  mismatches. Success: `ok: installed; waiting for first tick (<= 60s)`.
  The scheduler row reads `installed  waiting for tick` until a newer
  last_tick arrives.
- Uninstall: confirm `Nothing will fire on schedule until install. [y]
  uninstall [Esc]`. Success: the banner changes to `SCHEDULER NOT
  INSTALLED`.
- Failed: `failed: <error>`, verbatim.

---

## 6. State catalogue

**First launch, zero chores**

```
chores [1 Needs] 2 Chores 0 3 Runs 4 Usage 5 Inbox 6 System      14:05:12 +2s
tick 14:04:31 ok   -   no pause
 Nothing needs you.
 No chores defined. Definitions live in git; add one there, then run
   chores validate
```

Chores, Runs and Inbox each show one line: `No chores.` / `No runs.` / `No
notifications.`. Nothing else. The menu title is `[c]` and the header reads
`No chores defined`.

**Not installed** -- row 2 banner, reverse video:
`!! SCHEDULER NOT INSTALLED -- nothing fires on schedule.  6 System > install`
Queue row 1 is `!! scheduler not installed`. NEXT columns read `(not
installed)` in place of times, because a next_due that will not happen is
a lie.

**Scheduler stale**

```
chores [1 Needs !!1] 2 Chores 9 3 Runs 4 Usage 5 Inbox 3 6 System 14:05:12 +2s
!! SCHEDULER STALE -- last tick 09:12:04 (4h53m). Nothing is firing. 6 System
 LV CHORE                WHAT                                          SINCE
>!! scheduler            no tick for 293 intervals (60s); laptop woke 09:12
                         13:58 -- tick agent likely unloaded. install again
 !  inbox-triage         ...
```

NEXT times that have already passed show `overdue 14:00`. The "laptop
woke 13:58" wording comes only from the snapshot's warning text, if it
supplies one. It is never inferred.

**Global pause** -- banner row 2, reverse video:
`|| GLOBAL PAUSE "on a flight" since 06:40 -- nothing starts.  U resume`
The tab label still shows the count. NEXT columns read `paused`. Slots
during the pause become SKIPPED_PAUSED records in Runs. They are not
queued, and they feed Needs only after resume.

**Chore paused by breaker** -- ST `B`, NEXT `paused`, queue `!` row
`PAUSED by breaker: 3 consecutive failures`. The Chore header shows
`state PAUSED by breaker` plus the status run, and `u resume` in the key
line.

**Invalid definition** -- ST `X`, LAST `INVALID 14:04:31`, NEXT `--`.
The queue shows `!` with the first violation, and `+n more` when there are
several. The Chore header lists every violation. `r` is refused (no force).
`t` dry run still works and shows the same violations.

**Run in progress** -- ST `*`, LAST `RUNNING 14:00:02`. The Run view header
shows `RUNNING 5m10s` ticking with each poll. Transcript and stdout tail
live (the view sticks to the end until `k`/`g` scrolls away; `G`
re-follows). The key line gains `K kill`.

**Ended states** in lists and Run header (status word + reason, always both):
- KILLED: `KILLED  killed by operator` (`~`)
- TIMED_OUT: `TIMED_OUT  600s = timeout_sec` (`!`), with process group
  killed noted in reason
- BUDGET_EXCEEDED: `BUDGET_EXCEEDED  tokens 52,300 > budget 50,000` (`!`)
- OFFLINE: `OFFLINE  backend gateway unreachable -- no network, not a
  fault` (`~`)
- INTERRUPTED: `INTERRUPTED  process vanished without a verdict (lid
  closed or crash)` (`!`). `ended` shows `--`, never a guessed time.

**Missed slots after sleep** -- LAST `MISSED x2`. The queue shows `~`
`MISSED x2 while asleep 01:10-07:55, catch_up off -- not replayed`. With
catch_up on, the row says `MISSED x2 -> 1 catch-up run` and links to that
run.

**Battery deferral** -- LAST `DEFERRED_BATTERY`, NEXT `on AC power`. The
queue shows `~ held until AC power (slot 03:00)`. `r` is refused with the
option to force.

**Ceiling near / at exhaustion** -- Usage cell `52,300/60,000 87% ~`
becomes `60,000/60,000 100% !` at the ceiling. Near is `~` in the queue,
at the ceiling is `!`. The chore's NEXT shows `Sun 08:45 (ceiling)` when
its declared budget cannot fit. The menu's Usage submenu line ends with
`~` or `!`.

**Truncated run record** -- Run header `truncated  YES -- disk cap hit;
artifacts incomplete`. Every artifact tab label gets a `(trunc)` suffix,
and each pane ends with `-- truncated at disk cap --`. Lists add `T` after
the status word. The queue shows `~`.

**Ledger shrank** -- queue row 1 is
`!! ledger shrank from 4210 rows to 3900 since the last tick` (verbatim). It
appears in the System warnings too. The menu title is `!!1`. Runs lists
remain whatever the ledger now holds. Nothing is hidden or "fixed".

**Snapshot failed to load**

```
chores 1 Needs 2 Chores 3 Runs 4 Usage 5 Inbox 6 System   DATA OLD 3m02s
!! SNAPSHOT FAILED: <error text>. Showing 14:05:12. Retrying every 2s.
 (all content below is from 14:05:12, dimmed; actions disabled)
```

Actions refuse locally with `refused: no current snapshot`, because every
admission-dependent action needs current state. Dismiss is also held.
Navigation and reading still work.

---

## 7. Run record

Header facts first, then five artifact tabs and Compare, all in one view.
No artifact is ever mixed into another.

80x24, `pr-digest-20260926T154500Z-k3f9`, Transcript tab:

```
chores 1 Needs !3 [2 Chores 9] 3 Runs 4 Usage 5 Inbox 3 6 System 14:05:12 +2s
Chores > pr-digest > pr-digest-20260926T154500Z-k3f9
 BUDGET_EXCEEDED  tokens 52,300 > budget 50,000
 08:45:00 -> 08:52:09 (429s)   agent   agent-cli / backend default / subscr.
 tokens 44,100 in  8,200 out   turns 18   cpu 12.4s   disk 1.8 MB   exit 0
 rev a41c9e2-dirty (uncommitted changes)   truncated no
[Transcript 1240] Errors 1  Stdout 3  Stderr 0  Definition  Compare
    1 > {...}  collapsed JSON line, first keys shown
    2 > {...}
    3 > {...}
  ...
                                                          line 1 / 1240
Tab next tab  Enter expand  z all  / search  v pager  = compare  Esc back
```

160x48, the same run, Errors tab visible in a split (transcript left,
selected other artifact right):

```
chores  1 Needs !3  [2 Chores 9]  3 Runs  4 Usage  5 Inbox 3  6 System                                                              snapshot 14:05:12  +2s
Chores > pr-digest > pr-digest-20260926T154500Z-k3f9
 status   BUDGET_EXCEEDED   tokens 52,300 > budget 50,000                         chore    pr-digest (agent)
 started  08:45:00          ended 08:52:09   wall 429s                            backend  agent-cli   model backend default   billing subscription
 tokens   44,100 in   8,200 out   52,300 total   turns 18                         rev      a41c9e2-dirty (uncommitted)
 cpu      12.4s   disk 1.8 MB   exit 0   usd -- (subscription)                    truncated no
---------------------------------------------------------------------------------------------------------------------------------------------------------------
 [Transcript 1240]                                                                      | Transcript  [Errors 1]  Stdout 3  Stderr 0  Definition  Compare
    1  {...}                                                                            |    1  <errors.log line 1 -- content not in sample>
    2  {...}                                                                            |
  ...                                                                                   |
 1240  {...}                                                                            |
                                                                                        |
                                                                   line 1 / 1240        |
Tab next tab   ] right pane tab   Enter expand   z expand all   / search   n/N match   v pager   = compare   y yank id   Esc back
```

(The sample gives only line counts for the artifacts. Their content is not
drawn. `{...}` marks where each JSON line renders.)

**Header facts, in reading order:** the status and the reason (the one
line you came for); the time span; kind; backend / model / billing as
actually served; the usage dimensions (usd shows `-- (subscription)`
rather than 0); exit code; definition_rev, with `-dirty` spelled out as
`(uncommitted changes)` because it changes what the snapshot means; and
truncated.

**Tabs** (`Tab`/`Shift-Tab`, or a click; the count is the line count, and
`0` tabs are shown but dimmed):

- **Transcript** (`transcript.jsonl`). One row per JSON line: a
  right-aligned line number, then the line compacted to one row. Top-level
  keys print in file order, strings are clipped to the pane, and nested
  objects show as `{..n}` or `[..n]`. `Enter` expands the line to
  pretty-printed JSON in place, indented under its number. `z` toggles
  expand/collapse for all lines. `/` searches raw text across all 1,240
  lines. `n`/`N` step through matches, and the counter reads `match 3/17`.
  `g`/`G` and `Ctrl-d`/`Ctrl-u` page. `:` + number jumps to a line (`:880`).
  Lines are rendered lazily, so thousands of lines scroll at key-repeat
  speed. Lines that fail to parse are shown raw, prefixed `!json`. `v`
  opens the file in `$PAGER` for anything heavier. Secret values arrive
  redacted from the system and are shown as the file has them.
- **Errors** (`errors.log`). Plain text, line-numbered, wraps. It is a
  separate tab from stderr because they are separate files. 1 line here.
- **Stdout** / **Stderr**. Plain text, line-numbered, `w` toggles wrap.
  An empty file reads `(empty)`, never blank.
- **Definition** (`definition.md`). The exact snapshot the run used, shown
  verbatim with the rev in the pane title: `definition.md @ a41c9e2-dirty`.
- **Compare** (`=`). Pick the other run. The default is the chore's last
  SUCCEEDED run, and a picker lists this chore's runs with their revs.
  Shows a unified line diff of the two `definition.md` snapshots:

```
 Compare definition.md
   this run   pr-digest-20260926T154500Z-k3f9   a41c9e2-dirty   BUDGET_EXCEEDED
   other      pr-digest  Fri 08:45 (last success)  <rev>          SUCCEEDED
   1 line differs
 ------------------------------------------------------------------------
 - budget: {tokens: 60000}
 + budget: {tokens: 50000}
 ------------------------------------------------------------------------
 [=] pick another run    [u] unified / side-by-side (160 cols only)
```

The diff shows changed lines plus 3 lines of context each side. The
`-`/`+` prefixes carry the meaning, and colour only tints them. If the
snapshots are identical, it reads `definition identical -- difference is not
in the definition`. That is the point: a clean diff sends the operator to
the transcript.

---

## 8. CLI text output

No colour, no box drawing, fixed columns, and one fact per line in the
header blocks, so the output greps. It is honest when piped (no
truncation; long reasons wrap under their column). Times are local, with
the zone printed once.

### `chores status`

```
$ chores status
chores status at Sat 2026-09-26 14:05:12 PDT

scheduler  installed  tick 60s  last tick 14:04:31 (41s ago)  ok
ledger     4210 rows
pause      none
warnings   none

NEEDS YOU  3 alert  5 warn  1 info
  ALERT  inbox-triage          paused by breaker: 3 consecutive failures
                               (unread n-0412)
  ALERT  pr-digest             BUDGET_EXCEEDED 08:45:00: tokens 52,300 > budget
                               50,000 (unread n-0409)
  ALERT  notes-summarize       INVALID 14:04:31: budget lacks usd; backend
                               gateway has a usd ceiling
  WARN   log-brand-sweep       RUNNING since 14:00:02 (5m10s); usual 41s
  WARN   pr-digest             ceiling near: turns 18/20 (90%), tokens
                               52,300/60,000 (87%)
  WARN   release-notes-draft   SKIPPED_CEILING 13:00:01: usd 1.84 + 1.50 would
                               cross gateway ceiling 3.00
  WARN   workspace-gc          MISSED x2 (asleep 01:10-07:55), catch_up off
  WARN   weekly-gateway-smoke  OFFLINE Mon 09:00:04: backend gateway
                               unreachable
  INFO   pr-digest             3 PRs need your review (n-0408, 08:51:57)

CHORES  9 (1 running, 1 paused, 1 invalid, 1 disabled)
  ST  NAME                  KIND     BACKEND    LAST             AT          NEXT
  B   inbox-triage          agent    agent-cli  TIMED_OUT        12:00:00    paused
  X   notes-summarize       prompt   gateway    INVALID          14:04:31    -
      pr-digest             agent    agent-cli  BUDGET_EXCEEDED  08:45:00    Sun 08:45
  *   log-brand-sweep       command  -          RUNNING          14:00:02    14:30
      release-notes-draft   prompt   gateway    SKIPPED_CEILING  13:00:01    Mon 13:00
      workspace-gc          command  -          MISSED x2        03:00       Sun 03:00
      weekly-gateway-smoke  prompt   gateway    OFFLINE          Mon 09:00   Mon 09:00
      daily-local-smoke     prompt   local      SUCCEEDED        04:00:03    Sun 04:00
  -   repo-cleanup          command  -          SUCCEEDED        2026-08-30  disabled
  ST: * running  B paused by breaker  P paused by operator  X invalid  - disabled

USAGE  rolling 24h
  SCOPE      TOKENS                 USD             TURNS
  global     182,400 / 500,000 36%  1.84 / -        41 / 200 21%
  local       96,100 / -            - (unpriced)    -
  gateway     40,300 / 100,000 40%  1.84 / 3.00 61% -
  agent-cli   46,000 / -            - (subscr.)     41 / 150 27%
  pr-digest   52,300 / 60,000 87% ~ -               18 / 20 90% ~
  ~ near (>= 80%)   ! at ceiling
```

Exit status: 0 if there is nothing at `!!` or `!`, 1 if there are alerts,
2 for a system problem, and 3 if the snapshot failed. Scripts can gate on
it without `--json`.

### `chores runs --chore pr-digest`

```
$ chores runs --chore pr-digest
runs for pr-digest  newest first  window 30d  2 shown

STARTED              STATUS           WALL   TOK IN  TOK OUT  TURNS  USD  REV            RUN ID
2026-09-26 08:45:00  BUDGET_EXCEEDED  429s   44,100    8,200     18  -    a41c9e2-dirty  pr-digest-20260926T154500Z-k3f9
                     tokens 52,300 > budget 50,000
2026-09-25 08:45     SUCCEEDED        (usage, rev and run id: not in sample)

last success  2026-09-25 08:45
last failure  2026-09-26 08:45:00  BUDGET_EXCEEDED
```

The reason prints indented on the line under every non-SUCCEEDED row, and
is never clipped. The USD column reads `-` for subscription billing.

### `chores show pr-digest-20260926T154500Z-k3f9`

```
$ chores show pr-digest-20260926T154500Z-k3f9
run         pr-digest-20260926T154500Z-k3f9
chore       pr-digest
kind        agent
status      BUDGET_EXCEEDED
reason      tokens 52,300 > budget 50,000
started     2026-09-26 08:45:00 PDT
ended       2026-09-26 08:52:09 PDT
wall        429 s
backend     agent-cli
model       (backend default)
billing     subscription
tokens_in   44,100
tokens_out  8,200
usd         - (subscription)
turns       18
cpu         12.4 s
disk        1.8 MB
exit_code   0
rev         a41c9e2-dirty (uncommitted changes)
truncated   no

artifacts
  definition.md      snapshot of the definition this run used
  transcript.jsonl   1240 lines
  stdout.log         3 lines
  stderr.log         empty
  errors.log         1 line

read one:  chores show pr-digest-20260926T154500Z-k3f9 --artifact errors
```

`--artifact <name>` prints that artifact raw to stdout, with nothing else.
That is the piping path to `less`, `grep` and `jq`.

---

## 9. Traceability

| # | Story | Served by / status |
|---|---|---|
| D1 | write a definition -- runs, when, permissions, sandbox, backends -- in one place | Out of v1 for authoring ("Read-only over definitions"; git is the editor). Read back: Run > Definition tab, `chores show`. "Sandbox": data gap -- no sandbox field (and "No filesystem diffing ... (no sandbox)"). "Permissions": only allowed_tools exists. |
| D2 | commit to git; see every past version | Out of v1 for browsing versions (git does it; "Read-only over definitions"). Each run shows definition_rev (`-dirty` spelled out) in Run header, Runs REV column, CLI. |
| D3 | diff a definition between two runs | Run > Compare tab (`=`), default vs last success. |
| D4 | disable without deleting | Out of v1 as an action ("Read-only over definitions"; Domain 4 not supported). Shown: Chores ST `-`, NEXT `disabled`. |
| D5 | dry-run a task | `t` everywhere -> Dry-run plan overlay; menu opens it in Dashboard. |
| D6 | name which backends a task may use and may not | Data gap -- a chore has one `backend`; there is no allow/deny list. Shown: backend in Chores, Run header, dry run. |
| D7 | a task with no LLM alongside the others | kind `command` in every list (KIND column); usage cells read `-`. |
| D8 | copy an existing task | Out of v1 ("Read-only over definitions"; Domain 4 "copying ... not supported"). |
| D9 | before enabling, see allowed spend and run time | Dry run shows budget and applicable ceilings (dry run is always allowed, including when disabled). Data gap: timeout_sec is not in the snapshot or the dry-run plan list; it is visible only in a past run's definition.md. |
| R1 | rely on firing on schedule while awake | Scheduler health: row 2, System, menu title `STALE`/`OFF`; NEXT columns. |
| R2 | see a run was missed because asleep | MISSED records: Needs `~` row with count and window, Runs, Chore history, CLI. |
| R3 | run inside the named sandbox | Out of v1 -- "No filesystem diffing ... (no sandbox)". |
| R4 | use only the granted credentials | Not a surface (enforcement). Shown: secret names in dry run; values never ("Secrets never appear"). Data gap: no per-run record of secrets used. |
| R5 | stop at budget or timeout | BUDGET_EXCEEDED / TIMED_OUT with reason in Needs, lists, Run header, CLI. |
| R6 | no second run while one is going | SKIPPED_OVERLAP records; run-now overlap refusal (forceable, stated). |
| R7 | trigger a run by hand | `r` run now + Refusal overlay. |
| R8 | stop a running task | `K` kill with confirm; menu "Kill in Dashboard...". |
| R9 | the LLM finds out its remaining budget | Data gap -- no in-run budget query exists in the domain reference. No surface. |
| R10 | a task posts a message the operator sees | Chore-posted notifications: Inbox, Needs `i`/`!` rows, menu title and items. |
| G1 | a bad task cannot exhaust spend, tokens, disk, cpu | Budget/ceiling (tokens, usd, turns) shown in Usage and dry run; the disk cap shows as `truncated`. Data gap: no cpu bound (cpu_seconds is recorded, not capped). |
| G2 | per-task and global ceilings, smaller wins | Usage shows each scope; the dry-run verdict names the binding ceiling. Setting them is git (Read-only). |
| G3 | per-backend ceiling | Usage backend rows; refusal names the backend scope (release-notes-draft). |
| G4 | one kill switch stops every task and prevents starts | `P` pause all, with "[Tab] also kill running runs"; menu Pause All / Resume All; banner everywhere. |
| G5 | see a run was stopped for misbehaving, and why | Status + reason on every row and in Run header; KILLED/TIMED_OUT/BUDGET_EXCEEDED. |
| G6 | no credential ever in transcript, log, console | Not a surface; all surfaces display artifacts as stored, values redacted by the system ("Secrets never appear"). |
| G7 | a task cannot escalate its permissions or budget | Not a surface (enforcement). Shown: definition snapshot + rev per run; `-dirty` flagged. |
| G8 | told loudly after several failures in a row | Breaker pause -> alert notification -> macOS notification + menu `!` + Needs `!` row. |
| G9 | see what a task did to my filesystem | Out of v1 -- "No filesystem diffing". disk_bytes usage is shown. |
| W1 | every task, running now, last status, next run, one screen | Chores screen (`2`); CLI `status` CHORES block. |
| W2 | usage -- cpu, disk, tokens, spend -- per task and total | Usage (tokens/usd/turns per scope); Chore 24h sum row (cpu, disk from runs); Run header; System state dir size (total disk). |
| W3 | last success and last error per task | Chore pinned `last ok` / `last bad`; Chores 160 cols; menu item submenus. |
| W4 | see a posted message and dismiss it | Inbox + `d`; Needs `d`; menu Dismiss. |
| W5 | open the dashboard from the Dock | Launcher. |
| W6 | open from a terminal, same information as a TUI | `chores dash` is the same dashboard; Launcher just runs it. |
| W7 | glance at the menu bar, know if anything needs me | Glance title states + dropdowns. |
| W8 | dashboard -> a run's transcript in one step | `Enter` on a Needs run row opens Run at Transcript; `o` from any chore context. |
| W9 | tell at a glance which tasks are disabled | ST `-`, dim row, NEXT `disabled`, sorted last; `state:disabled` filter. |
| V1 | every past run: when, how ended, cost | Chore history, Runs screen, `chores runs`. |
| V2 | transcript, errors, console output as three things | Run tabs Transcript / Errors / Stdout / Stderr (console kept as its two streams). |
| V3 | pull transcripts/outputs for one run, a set, a date range, from a script | CLI `--json` (not designed here) and `chores show --artifact`; the queries exist in the domain reference. |
| V4 | compare a run against the exact definition that produced it | Run > Definition tab (definition.md @ rev). |
| V5 | last success and last failure without scrolling | Chore pinned lines (from snapshot); `chores runs` footer. |
| V6 | which runs last month blew budget, timed out, errored | Runs screen, preset F3 / query `30d status:...`; CLI `chores runs` filters. |
| V7 | feed a set of runs to an LLM for patterns | No dashboard element (Actions are "the list in Domain reference 4, nothing more"). Path: `chores runs --json` piped by the operator (or into a chore). |
| V8 | tell which backend and model served a run | Run header backend / model / billing; Runs 160 cols; `chores show`. |
| X1 | on a flight, see cloud tasks failed fast for no network | OFFLINE ranked `~` with "no network, not a fault"; global pause "on a flight". |
| X2 | a local-model task keeps running offline | Nothing to design beyond: local chores keep SUCCEEDED rows while gateway ones read OFFLINE; backend column makes the split visible. |
| X3 | heavy tasks defer on battery | DEFERRED_BATTERY rows, NEXT `on AC power`; run-now battery refusal (forceable). |
| X4 | stale information never reads as fresh | Snapshot age on row 1, `DATA OLD` + dimming; menu `?`; separate scheduler freshness. |
| X5 | close the lid mid-run, get an honest record | INTERRUPTED with `ended --`, never a guessed end. |
| X6 | back online, missed runs reported not fired at once | MISSED xN records with catch_up stated; Needs `~` row. |

---

## 10. Rejected alternatives

- Landing on the full chores table -- at 40+ chores the table spreads the
  answer out; the operator asked for the queue.
- Merging a chore's conditions into one worst-state row -- hides the second
  problem (pr-digest is both BUDGET_EXCEEDED and near ceiling).
- Treating OFFLINE and KILLED as alerts -- they would train the operator to
  ignore `!` on every flight.
- A dashboard-local "acknowledge" for failed runs -- invents state the
  domain does not have; it is an open question instead.
- A Dock badge with the alert count -- a second glance surface that
  disagrees with the menu bar between polls; the menu bar is the one glance.
- Actions (run, kill, pause with reason) directly in the menu -- a native
  menu cannot show a refusal or take a reason; they open the dashboard.
- Colour-only status (red/amber/green dots) -- fails NO_COLOR and pipes.
- Single-letter status abbreviations in lists (F, T, B) -- ambiguous
  (B = breaker or budget); full status words fit in 16 columns.
- A command palette (`:`) for all actions -- makes two ways to do each
  thing; rare actions live only on System.
- A spend chart over weeks -- no metrics backend; the trend band is a
  median comparison computed from run records.
- Merging stderr into errors, or stdout and stderr into one "console" --
  they are separate files and the story asks for separation.
- Pretty-rendering the transcript as a chat -- the JSON-lines schema is not
  in the domain reference; a generic JSON-lines viewer cannot lie.
- Auto-following to a new screen when the menu deep-links into an open
  dashboard with an overlay up -- the target is pushed behind the overlay
  instead, never discarding what the operator was doing.

---

## 11. Open questions

1. **Can the operator acknowledge a failed run so it leaves the queue
   before the next run?** Default: no; it clears on the next SUCCEEDED.
   A weekly chore's OFFLINE therefore sits at `~` for a week.
2. **Can "run now" start a DISABLED chore?** Default: no -- refused, not
   forceable: "disabled in git". (Domain 4 does not say.)
3. **What is "well past normal" for RUNNING?** Default: > 3x the median of
   the last 10 SUCCEEDED wall times and > 60 s; none flagged with < 3
   successful runs.
4. **Near-ceiling threshold.** Default: 80% of any dimension of any scope.
5. **Trend flag threshold for "out of pattern".** Default: > 2x the 7-day
   median for the same 24h window, minimum 7 days of history.
6. **Should info messages raise a macOS notification?** Default: no; only
   alerts do (as the domain says), info changes the title only.
7. **Does the transcript JSON-lines format have stable keys (role, turn,
   tool) the viewer can structure by?** Default: no; generic viewer.
8. **Should SKIPPED_PAUSED records during a global pause surface in Needs
   after resume?** Default: yes, as one `~` row per chore with a count.
9. **Launcher: which terminal app?** Default: the user's default
   terminal for `.command` files (Terminal.app); iTerm2 when set as the
   macOS default handler.

---

## Launcher (Dock tile)

Click, no dashboard open:

1. The Dock tile bounces once. A terminal window opens titled `chores`,
   sized 160x48 if the screen allows, otherwise the terminal's default.
2. The first frame, within 100 ms: row 1 is the tab bar with every count
   shown as `..`, row 2 reads `reading status...`, and the rest is blank.
   No logo, no splash.
3. When the snapshot returns (< 500 ms), the Needs screen paints in place.
   If it takes over 2 s, row 2 reads `reading status... 2s (4210 ledger
   rows)` using the last known count, or without the count on first ever
   launch.
4. If the snapshot fails: the failed-snapshot state (section 6), with no
   last-good data. Row 3 shows the error and `Ctrl-r to retry`.

Click, dashboard already open: the existing terminal window comes to the
front, on its current screen, cursor and overlay unchanged. No second
instance ever starts. The dashboard flashes row 1 in reverse video for one
poll, so the operator sees which window answered. Menu deep links (`Open in
Dashboard` on an item) use the same path, and then navigate the existing
dashboard to the item, pushed onto its back-stack.

Quitting the dashboard (`q`) closes the terminal window that the Launcher
opened. A dashboard started by hand in a terminal leaves its shell alone.
