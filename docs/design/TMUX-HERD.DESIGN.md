# tmux-herd -- prune idle tmux sessions, name the rest after what they run

> **Status:** DRAFT
> **Date:** 2026-09-18
> **Authors:** Todd (intent), Claude (draft)
> **Depends on:** [LOG-HOARDER](./LOG-HOARDER.DESIGN.md) (sibling; shares nothing but the tmux server)

---

## Overview

A laptop accumulates dozens of tmux sessions: some are bare shells left at
a prompt, most host a coding agent (claude, codex, opencode) working in a
directory that is often not the one the session started in, on a repo that
may be a worktree. `bin/tmux-herd` walks every session, kills the ones that
are provably idle, and renames the rest to a hierarchical name that says
which agent, which repo, which branch, and what it is doing -- so the right
session is findable from `tmux ls` and the chooser without attaching to it.

`bin/tmux_shepherd.sh` already exists and is the log-hoarder archiver; this
tool is deliberately named `tmux-herd` to avoid that collision.

---

## Goals

1. **Fewer sessions** -- after a run, every surviving session either hosts a
   non-shell process or has an attached client. Idle detached sessions are
   gone.
2. **Names that locate** -- every surviving session is named
   `<agent>@<repo-path>=<branch>[+<slug>]` (grammar below), so sessions on
   the same repo sort together and worktrees of one repo sort adjacent.
3. **Labels that describe** -- the `+<slug>` part reflects the agent's
   CURRENT task, sourced from the agent's own session record, not from the
   directory name.
4. **Safe by default** -- the default run is a dry run that prints the
   plan; `-y` applies it. Nothing is killed that has an attached client or
   a non-shell foreground process, ever.
5. **Cross-platform** -- zsh, runs on macOS (primary) and Linux; process
   inspection through `ps` and `lsof`/`/proc` behind one seam.
6. **Idempotent** -- a second run over an already-herded server is a no-op
   and says so.

## Non-Goals

- **Not a tmux status line or TUI** -- it is a batch tool; the chooser
  (`prefix s`) is the UI.
- **Not a log branding replacement** -- log-hoarder's `log_brander` slugs
  archived logs after the fact; tmux-herd labels live sessions. Neither
  calls the other.
- **Not an agent controller** -- it never sends keys to a pane or
  interrupts an agent.
- **No LLM in the loop** -- labels come from structured session records
  and text heuristics. An LLM summarizer is a Future Consideration.
- **Not a window-level tool** -- windows and panes inside a session are
  read to classify the session; they are never renamed or closed.

---

## Architecture Overview

```
  +--------------------+     +------------------------+     +-----------------+
  |  tmux adapter      |     |  classifier (core)     |     |  tmux adapter   |
  |  list-panes -a     |---->|  session -> verdict    |---->|  kill-session   |
  |  session_attached  |     |  IDLE | KEEP | AGENT   |     |  rename-session |
  +--------------------+     +-----------+------------+     +-----------------+
                                         |
                    +--------------------+--------------------+
                    |                    |                     |
           +--------v-------+   +--------v-------+   +---------v---------+
           | proc adapter   |   | git adapter    |   | agent probes      |
           | tree, cwd, cmd |   | toplevel,      |   | claude / codex /  |
           | (ps, lsof|proc)|   | common-dir,    |   | opencode -> slug  |
           +----------------+   | branch, origin |   +-------------------+
                                +----------------+
```

Dependency direction: the classifier and the namer are pure functions over
text the adapters hand them. Adapters are the only place `tmux`, `ps`,
`lsof`, `git`, or `$HOME/.claude` appear. The whole thing is one zsh file
(`bin/tmux-herd`) with the sections labelled per AGENT.md; the seams are
function boundaries, not files.

---

## Design

### Discovery (tmux adapter)

One call gathers everything the classifier needs, one pane per line:

```
tmux list-panes -a -F \
  '#{session_name}\t#{session_attached}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_dead}'
```

The tool's own session (`$TMUX` pane) is always KEEP, whatever it holds.

### Process inspection (proc adapter)

| Need | macOS | Linux |
|------|-------|-------|
| descendants of `pane_pid` | `ps -axo pid=,ppid=,comm=,args=` walked in-shell | same |
| cwd of a process | `lsof -a -p PID -d cwd -Fn` | `readlink /proc/PID/cwd` |

`ps` output is fetched once per run and walked in memory; one `lsof` per
agent process, never per pane.

### Classification (core)

A session's verdict is the max over its panes of:

| pane state | verdict |
|------------|---------|
| `pane_dead=1` | IDLE |
| foreground command is a shell (`zsh bash sh fish`) and the pane pid has no descendants | IDLE |
| foreground is a shell with descendants, none of them an agent | KEEP (e.g. `vim`, `make`, an ssh) |
| any descendant is an agent binary (`claude`, `codex`, `opencode`, or a `node` whose argv names one) | AGENT |

Session verdict: AGENT > KEEP > IDLE. `session_attached=1` promotes IDLE to
KEEP. Only IDLE sessions are killed.

The classifier takes the pane lines and a `pid -> (ppid, comm, args)` table
as input, so the smoketest drives it with fixture text and never a live
tmux server.

### Location (git adapter)

For AGENT sessions the location is the agent process's cwd, not the pane's
`pane_current_path` (the agent may have `cd`'d, and a shell in the same
window may be elsewhere). For KEEP sessions it is the pane path.

```
toplevel   = git -C cwd rev-parse --show-toplevel
common     = git -C cwd rev-parse --git-common-dir      # main repo for a worktree
branch     = git -C cwd rev-parse --abbrev-ref HEAD      # or "detached" / short sha
repo-path  = dirname(common) made relative to ~/workplace, else to ~
```

Using the COMMON dir is what groups worktrees: a worktree at
`~/workplace/.worktrees/tds-utils-yellow` resolves to
`9atatimer/tds-utils`, the same prefix as the primary checkout, and only the
`=branch` differs. Non-git cwd: repo-path is the cwd relative to `~`,
branch is empty.

### Agent probes (one per agent, behind one interface)

`probe_<agent> <pid> <cwd>` prints a slug or nothing. Order of preference
inside each probe: the agent's own structured record, then the pane's
visible text, then nothing.

| agent | record | fields used |
|-------|--------|-------------|
| claude | newest `~/.claude/projects/<cwd with / -> ->>/*.jsonl` whose mtime >= the process start time | `summary` (type=summary), else `slug`, else first `user` message text |
| codex | newest `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` whose `cwd` field matches | first `user` message text |
| opencode | `~/.local/share/opencode/` session store for that project | session title |
| any | `tmux capture-pane -p -S -40` on the agent pane | last non-empty line that is not a prompt or status bar |

The slug is the source text lowercased, non-`[a-z0-9]` runs collapsed to
`-`, truncated to the first 4 words / 32 chars.

Matching a transcript to a process by cwd + mtime >= start time is a
heuristic; two claude sessions in one directory may swap slugs. That is
accepted (see Key Decisions) -- the branch part is exact, the slug is a
hint.

### Naming (core)

```
name := <agent>@<repo-path>[=<branch>][+<slug>][-<n>]

agent      : claude | codex | opencode | sh (KEEP sessions with no agent)
repo-path  : path relative to ~/workplace (e.g. 9atatimer/tds-utils),
             else relative to ~ with a leading ~ (e.g. ~/Downloads)
branch     : git branch; "." and ":" -> "_" (tmux rejects both)
slug       : per Agent probes; omitted when empty
-n         : 2.. appended only on collision with another live session
```

Examples, as `tmux ls` sorts them:

```
claude@9atatimer/tds-utils=feature/yellow-flowers+tmux-herd-design
claude@9atatimer/tds-utils=master+fix-release-link
codex@9atatimer/quillmap=main+import-parser
sh@~/Downloads
```

`/` is legal in tmux names and gives the chooser its hierarchy. `.` and
`:` are the only characters tmux refuses (verified on tmux 3.4:
`a.b` is silently stored as `a_b`, `a:b` is rejected), so the user's
sketched `path:branch` becomes `path=branch`.

A session whose current name already equals its computed name is left
alone; a session the user has renamed by hand is NOT protected -- the
computed name wins, because the tool has no way to tell a hand name from a
stale one. `-k <pattern>` excludes sessions from renaming and killing.

### CLI

```
tmux-herd [-n] [-y] [-k pattern] [-v]
  -n   dry run (default): print the plan, change nothing
  -y   apply: kill IDLE, rename AGENT and KEEP
  -k   keep: never kill or rename sessions matching this glob (repeatable)
  -v   show per-pane evidence behind each verdict
```

Plan output, one line per session, stable for diffing:

```
KILL    scratch-3            (idle: zsh, no children, detached)
KEEP    sh@~/Downloads       <- 5                (attached)
RENAME  claude@9atatimer/tds-utils=master+fix-release-link  <- 7
SAME    claude@9atatimer/tds-utils=feature/yellow-flowers+tmux-herd-design
```

Exit 0 when the plan is empty or applied; 1 when `tmux` is unreachable.

---

## State Machine

Sessions have no lifecycle inside this tool beyond one verdict per run:

```
 +-------+   dead / idle shell, detached   +------+
 | pane  |-------------------------------->| IDLE |--(-y)--> kill-session
 +-------+                                 +------+
     |  shell with non-agent children,      +------+
     |  or attached                          | KEEP |--(-y)--> rename sh@...
     +------------------------------------->+------+
     |  agent process in tree               +-------+
     +------------------------------------->| AGENT |--(-y)--> rename <agent>@...
                                            +-------+
```

| From | To | Trigger | Condition |
|------|----|---------|-----------|
| pane | IDLE | classify | dead, or shell fg with no descendants |
| IDLE | KEEP | classify | `session_attached=1`, or `-k` match, or own session |
| pane | KEEP | classify | non-agent descendants |
| pane | AGENT | classify | agent binary among descendants |

---

## Data Model

Nothing persisted. Two in-memory tables for the run:

```
pane
+-- session        string   tmux session name
+-- attached       0|1
+-- pid            int      pane_pid
+-- fg_cmd         string   pane_current_command
+-- path           string   pane_current_path
+-- dead           0|1

session_plan
+-- session        string
+-- verdict        IDLE | KEEP | AGENT
+-- agent          claude | codex | opencode | sh
+-- agent_pid      int      (AGENT only)
+-- cwd            string
+-- repo_path      string
+-- branch         string
+-- slug           string
+-- new_name       string
+-- action         KILL | RENAME | SAME | KEEP
```

## Data Warehouse

Nothing is ledgered. The plan is printed and discarded; the tmux server is
the only state, and `tmux ls` before and after is the audit trail.

---

## Security Considerations

- **Reads agent transcripts** -- `~/.claude/projects/*.jsonl` and peers
  hold prompt text. The tool reads only the fields named above, keeps
  nothing, and emits at most a 32-char slug into a tmux session name,
  which is visible to anyone who can see the terminal already.
- **Kills processes** -- only sessions whose every pane is a childless
  shell or dead. A shell with any descendant is never killed, so a
  backgrounded `&` job protects its session.
- **No network, no secrets, no privilege.**

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Idle test | childless shell foreground, detached | Provable from `ps`; no capture-pane text parsing, no false kills on a paused `less` |
| Location source for agents | the agent process's cwd, not the pane path | The user's stated failure mode: agents on repos that are not the dir the session started in |
| Worktree grouping | `git-common-dir` gives the repo path, `HEAD` gives the branch | Worktrees of one repo share a prefix and differ only in `=branch` |
| Name separators | `@` agent, `/` path, `=` branch, `+` slug | `.` and `:` are the only tmux-illegal characters; `=` and `+` are legal, unambiguous, and shell-safe unquoted in `tmux attach -t` |
| Slug source | agent's own session record first, pane text second | Structured, current, and per-session; pane text is the fallback for agents with no readable store |
| Slug heuristic mismatch | accepted | branch and path are exact; a swapped slug between two agents in one dir costs a glance, an LLM would cost a dependency |
| Agent probe seam | one function per agent, same signature | Adding an agent is one function and one entry in the detection list |
| Dry run default | yes | Kills are irreversible; the plan is cheap to read |
| Hand-renamed sessions | not protected; use `-k` | No reliable signal distinguishes a hand name from a stale computed one |
| One file | `bin/tmux-herd`, zsh | Matches every sibling in `bin/`; the seams are function boundaries per AGENT.md's script structure |

## Open Questions

1. Whether the claude transcript's `summary` records are reliably present
   for a session in progress, or only written at compaction; if the latter,
   `slug` / first user message will carry most of the labelling.
2. Whether to kill sessions whose only process is an agent that has
   exited to a shell prompt after finishing (they classify IDLE today and
   will be killed, which is the intent, but their transcript is the only
   record of what they did).
3. Whether the opencode store is readable without the `opencode` binary
   (sqlite vs json); if not, opencode falls back to pane text.

## Rejections

- **LLM-generated labels via `log_brander`** -- adds an Ollama dependency
  and latency per session for a label the agent's own record already
  holds; and `log_brander` is itself a stub with no endpoint.
- **`pane_current_path` as the location** -- wrong whenever the agent
  changed directory, which is the case the tool exists for.
- **Parsing `capture-pane` text to detect idleness** -- prompt strings are
  per-user and per-theme; a childless shell is a fact.
- **Renaming windows too** -- the chooser already shows window names;
  session names are the unit the user navigates by.
- **`:` in names** -- tmux uses it as the target separator and rejects it.
- **A persistent state file to protect hand-renamed sessions** -- state
  that drifts from the tmux server is worse than no state; `-k` covers it.
- **Python** -- everything needed is `ps`, `git`, `tmux`, and string
  munging; zsh keeps it on the same footing as the rest of `bin/`.

## Future Considerations

- A tmux hook (`client-attached`) or a chores entry to run `tmux-herd -y`
  on a schedule.
- An LLM summarizer as a fourth slug source when a local endpoint exists.
- Window naming inside AGENT sessions (`agent`, `shell`, `logs`).

## Related Documents

- [LOG-HOARDER.DESIGN.md](./LOG-HOARDER.DESIGN.md) -- the other tmux-adjacent
  tool; owns `bin/tmux_shepherd.sh` and `bin/tmux_logging.sh`.
- [CHORES.DESIGN.md](./CHORES.DESIGN.md) -- the scheduler that could run
  this on a cadence.
