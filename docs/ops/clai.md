# clai -- runbook

How each coding agent on this machine gets its instructions, hooks, skills
and MCP servers, and how to check and repair that. The agents in use are
claude, codex, opencode and omp; agy is out of use (Issue#794).

- clai itself (the launcher, `clai provision`): template-tools
  `packages/clai`, design record `packages/clai/docs/CLAI.DESIGN.md`,
  install and upgrade `packages/clai/docs/SKILL.CLAI.md`.
- Policy for changing an agent's configuration: the `clai` skill.
- This repo's part: `clai.d/` (the global hook tree, linked as
  `~/clai.d`), `bin/agent-instructions`, `bin/clai-health`,
  `bin/agent-load`, `bin/codex-session-cost`.
- Tests: `test/smoketest_agent_instructions.sh`,
  `test/smoketest_clai_health.sh`, `test/smoketest_agent_load.sh`,
  `test/smoketest_codex_session_cost.sh`, and the agent-instructions
  cases in `test/smoketest_release.sh`. All are hermetic and run in
  `dist-ci`.

---

## What reaches an agent, and from where

| What | Source | How it gets there | When |
|---|---|---|---|
| Global instructions | `clai.d/AGENT.global.md` (every agent) plus `clai.d/<agent>/AGENT.<agent>.md` (that agent only, when it exists) | `bin/agent-instructions` joins them, without their HTML comment blocks, into `~/.local/share/tds-utils/agents/<agent>.md` and points the agent's link there; `README.md` beside them says they are built | when `bin/tds-release` advances the public unit (the released `bin/tds-post-release` runs it); otherwise run `agent-instructions` |
| Repo instructions | the repo's `AGENT.md` (`CLAUDE.md` and `AGENTS.md` are symlinks to it) | the agent reads it from the repo | every session |
| Skills | the Skills repo, acquired by `lmde acquire` | `clai provision` copies or links them into `.claude/skills`, `.codex/skills` and `.agents/skills` in each project | every `clai <agent>` launch (`clai.d/<agent>/pre/05-provision`) and every session-start hook |
| MCP servers | the Skills repo's `mcp/manifest.json`, overlaid by `clai.d/mcp.json` | `clai provision` writes each agent's own config dialect | same as skills |
| Agent settings | `clai.d/<agent>/pre/` hooks | each hook merges only the keys it owns into the agent's config | every `clai <agent>` launch |

Each agent reads its global instructions from one place:

| agent | link | config |
|---|---|---|
| claude | `~/.claude/CLAUDE.md` | `~/.claude.json` |
| codex | `~/.codex/AGENTS.md` | `~/.codex/config.toml` |
| opencode | `~/.config/opencode/AGENTS.md` | `~/.config/opencode/opencode.json` |
| omp | `~/.omp/agent/AGENTS.md` | `~/.omp/agent/config.yml` |

The desktop apps (Claude Code, Codex) do not start through clai, so a
`clai.d/<agent>/pre/` hook runs only on the next `clai <agent>` launch.
That is why the instruction files are built at release, not by a hook.

Skills have the same gap. The Codex app runs neither `lmde acquire` nor
`clai provision`, so a repo or worktree that only Codex opens keeps the
skills it last got: after a skills release run `lmde acquire`, then
`clai provision` in it, and run `clai provision` in every new worktree.
Codex does not send a fresh skill list when the app reopens a
conversation, so do not count on a running conversation to see a new
skill; start a new one, or have the agent read the `SKILL.md` by path
(the `clai` skill, "When an agent sees new skills"). If `clai provision`
refuses unedited skills as "local edits", that is template-tools
Issue#1137.

## Check the wiring

```
clai-health            # one row per agent, for the repo you are in
clai-health -r <repo>  # for another repo
```

Exit 0 when every installed agent's instructions are current, 1 when one
is not. `stale` means the built file is older than its source, or the
agent's link does not point at it. `not installed` means the directory the
link lives in does not exist.

`agent-load` reports the bytes each agent loads at session start against
a 32 KiB budget; `codex-session-cost` reports what one Codex session cost.
Both have their runbook in `docs/ops/agent-load.md`.

## Repair the instructions

```
agent-instructions -n      # what would change
agent-instructions         # build every installed agent's file and link it
agent-instructions check   # exit 1 if anything is stale or wrong
agent-instructions -a codex
```

It reads the source next to the script, so run the copy in the release
worktree (`~/.tds/release/bin`, which is on `PATH`), never a topic
checkout's, unless you mean to try that checkout's text. A regular file
at an agent's link is never overwritten: move it aside, then run it
again.

## Codex's model

`clai.d/codex/pre/30-model` owns the two top-level keys `model` and
`model_reasoning_effort` in `~/.codex/config.toml`: `gpt-6.1-terra` at
`medium`, the owner's choice for cost. 6.1-terra's own default effort is
low, so the hook always writes the effort. It changes nothing else in the
file, so a profile keeps its own model. `CLAI_CODEX_MODEL` and
`CLAI_CODEX_REASONING_EFFORT` override it for one launch; a value that is
not a plain model or effort name is refused.

The edit needs `python3` with `tomllib` (Python 3.11 or later) first on
`PATH`; with the stock macOS Python 3.9 the hook says so and changes
nothing. It writes the file only when the result reads back as the original
with exactly those two keys set, so it never edits inside a multi-line
string. A symlinked `config.toml` is edited in its target, and the file
keeps its mode.

The hook runs on `clai codex`. The Codex desktop app does not start
through clai, but it reads the same file, so it picks the model up on its
next start after any `clai codex` launch. To apply it without launching
Codex, run the hook directly: `~/clai.d/codex/pre/30-model`.

## Give one agent a rule no other agent should load

Write it in `clai.d/<agent>/AGENT.<agent>.md`, in the same style as the
global file, land it, and run `bin/tds-release`. Only that agent's built
file carries it. Claude Code has one (`clai.d/claude/AGENT.claude.md`):
the rules that name Claude Code's own tools. A fragment starts with an
`<!-- AGENT.<agent>.md` header comment, and `test/smoketest_agent_global.sh`
checks it like the core.

Keep the core short: every agent loads it in every repo.
`test/smoketest_agent_budget.sh` builds every agent's file from the
checkout and fails when one, plus this repo's `AGENT.md`, passes the
`agent-load` budget.

## Add an agent

The `clai` skill, "Adding a coding agent", is the procedure. In this
repo, also add a line for it to `link_rel` in `bin/agent-instructions`,
to `agent_facts` in `bin/clai-health`, and to `agent_files` in
`bin/agent-load`, and run `agent-instructions -a <agent>`.

## Known limits

- `agent-instructions` creates a link only where the agent's config
  directory already exists; install the agent first.
- `clai-health` reports whether ast-mcp is named in the agent's config
  file, not whether the server starts.
- Codex's model is read from the top-level `model` key of
  `~/.codex/config.toml`; a profile that overrides it is not shown.
