# agent-load and codex-session-cost -- runbook

Two read-only tools that measure what coding agents spend on instructions.
Use them before and after a change to an instruction file or a skill, and
put their output in the PR body.

- `bin/agent-load` (bash) reports what each agent loads at session start
  in one repo: its global instruction file, the repo instruction file, and
  the skills it is offered.
- `bin/codex-session-cost` (Python 3, standard library only) reports what
  one Codex session cost, from the rollout log Codex writes.
- Tests: `test/smoketest_agent_load.sh` and
  `test/smoketest_codex_session_cost.sh`. Both are hermetic and run in
  `dist-ci.yml`.

---

## Install

Nothing to install. Both scripts are in `bin/`, which is on `PATH` after
`bin/tds-release`. `codex-session-cost` needs `python3` 3.10 or later.

## agent-load

```
agent-load [-r repo] [-b budget-bytes] [-a agent]
```

- `-r` is the repo root. The default is the git top level of the current
  directory.
- `-b` is the byte budget for the global file plus the repo file. The
  default is 32768: Codex stops reading project instruction files there by
  default, and the agent-instructions skill sets the same target for all
  instruction files one session loads.
- `-a` reports one agent only: `claude`, `codex`, `opencode` or `omp`.

It prints a markdown table, one row per agent. The global file column
names the `$HOME` file and, when it is a symlink, the file it points to,
whose bytes are counted. The skills columns count the `SKILL.md` files in
the agent's skills directory in the repo and add up the bytes of their
one-line `description`. Every session carries that list of descriptions,
so its size is a cost of every session too. Paths under `$HOME` print
from `~`, so the output can go in a public PR body.

Exit status: 0 when every agent is within the budget, 1 when any agent is
over it, 2 for a usage error. A gate can use the exit status directly.

Where each agent reads its files is the function `agent_files`. Change it
there when an agent's files move.

| agent | global file | repo file | skills directory, in the repo |
|-------|-------------|-----------|------------------|
| claude | `~/.claude/CLAUDE.md` | `CLAUDE.md` | `.claude/skills` |
| codex | `~/.codex/AGENTS.md` | `AGENTS.md` | `.codex/skills` |
| opencode | `~/.config/opencode/AGENTS.md` | `AGENTS.md` | `.claude/skills` |
| omp | `~/.omp/agent/AGENTS.md` | `AGENTS.md` | not known; shown as `-` |

## codex-session-cost

```
codex-session-cost <rollout.jsonl>
codex-session-cost --latest [--cwd <dir>]
```

Codex writes one rollout log per session under
`$CODEX_HOME/sessions/YYYY/MM/DD/` (`CODEX_HOME` defaults to `~/.codex`).
`--latest` reads the newest log, and `--cwd` limits it to sessions started
in that directory.

The report:

- `kind`: `main`, or `auto-review` for a session Codex starts to judge
  whether an action may run. Auto-review sessions load the same AGENTS
  block as the session they judge.
- `agents block`: characters of the global and repo instruction files as
  Codex sent them. Codex sends this block again with every turn.
- `skills list`: characters of the skill list Codex sent.
- `tool calls`: the number of tool calls and the characters of output they
  returned.
- `skill calls`: the tool calls whose text names a skill's `SKILL.md`, and
  the output they returned; then one line per skill with its call count
  and the output of those calls, marked `(repeat)` above one. A call that
  names two skills counts its whole output toward each, so the per-skill
  lines can add up to more than the total.

Paths under `$HOME` print from `~`, and control characters in the log
print as `?`, so the report can go in a public PR body and a log cannot
send escape sequences to the terminal.
- `tokens`: the session totals from the last token count in the log.
  `uncached` is input minus cached.

Exit status: 0, or 2 when no log is found.

## Known limits

- `agent-load` counts files, not what each harness does with them. It
  does not follow Claude `@` imports, and it reads only the repo root's
  instruction file, not ones in subdirectories that some agents also load.
- `agent-load` counts only the skills directory in the repo. It does not
  count user-level or plugin skills, such as `~/.codex/skills/.system`,
  which Codex also lists, so the skills columns can be lower than what an
  agent is offered.
- `agent-load` reads the description only when it is on one line of the
  frontmatter.
- `codex-session-cost` counts a call that names a `SKILL.md` whether the
  call reads it or writes it. A skill the session is editing shows many
  calls; read the skill name before calling it waste.
- `codex-session-cost` depends on Codex's log format: the
  `# AGENTS.md instructions` and `<skills_instructions>` prefixes and the
  auto-review prompt text. When Codex changes them, the matching line
  reads 0 or `main`; update the constants at the top of the script.

## Disable

Nothing runs on its own. To stop CI from running the tests, remove their
two steps from `dist-ci.yml` in a PR.
