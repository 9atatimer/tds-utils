# clai — CLI AI launcher with overlay hooks

## Purpose

Thin wrapper around interactive AI CLI agents (`claude`, `gemini`, `codex`, …)
that runs pre- and post-hooks discovered from a directory walk. Born to solve:
"keep Cloudflare MCPs defined globally but disabled by default for new
projects" — but the hook framework is general.

## Invocation

```
clai <agent> [args...]    # launch <agent> with its pre/post hooks
clai --list-agents        # list agents that have hooks configured
clai --help               # show usage
```

Runs all pre-hooks for `<agent>`, then `exec`s `<agent> [args...]`. Post-hooks
fire after the agent exits.

`--list-agents` (`-l`) walks `$PWD` -> `$HOME` and prints, sorted and
de-duplicated, the name of every agent that has a `clai.d/<agent>/` directory
on that walk -- i.e. the agents you have hooks configured for. Names go to
stdout (pipeable); a "none found" note goes to stderr. `--help` (`-h`) prints
usage.

## Hook discovery -- overlay walk

Walk from `$PWD` upward to `$HOME` **inclusive**. At each directory level, if
`clai.d/<agent>/<stage>/` exists, its contents contribute to the hook set for
that stage.

Stages: `pre`, `post`.

**Stop condition:** the walk halts at `$HOME`. If `$PWD` is not within `$HOME`
(e.g. `/tmp`), only `~/clai.d/` is consulted — never walk above `$HOME`, never
walk paths outside it.

**Merge semantics — override-by-filename:**
- Same basename at multiple levels → closer-to-`$PWD` wins.
- A zero-byte file at a closer level nulls out a deeper hook of that name (you
  can shadow a global hook to disable it in one project).

**Run order:** alphabetical by basename across the merged set. Numeric prefixes
(`10-foo`, `20-bar`) give explicit ordering.

## Hook contract

Each hook is an executable file. `clai` invokes it directly (must have its own
shebang). The hook receives in the environment:

| Var          | Meaning                                  |
| ------------ | ---------------------------------------- |
| `CLAI_AGENT` | The agent name (`claude`, `gemini`, …)   |
| `CLAI_CWD`   | The directory `clai` was launched in     |
| `CLAI_ARGS`  | The agent's argv, space-joined, shell-quoted |
| `CLAI_STAGE` | `pre` or `post`                          |
| `CLAI_EXIT`  | (post-hooks only) the agent's exit code  |

The hook's own working directory is `$CLAI_CWD`.

**Failure semantics:**
- Pre-hook non-zero exit → abort. Agent is not launched. Post-hooks do not run.
- Post-hook non-zero exit → logged to stderr, walk continues. `clai` propagates
  the agent's exit code, not the hook's.

## Layout

In the tds-utils repo:

```
bin/clai                              # entry point (zsh on macOS, bash on linux per repo convention)
clai.d/                               # default hooks shipped with tds-utils
  claude/
    pre/
      10-disable-cloudflare-mcp       # default hook for the original use case
test/smoketest_clai/                   # smoke tests
```

User installation (per the repo's dot.* convention): `~/clai.d/` is symlinked
to `tds-utils/clai.d/` so global hooks are version-controlled. Project-scoped
hooks live in `<repo>/clai.d/` and are committed alongside the project.

## The cloudflare-mcp hook (concretely)

`clai.d/claude/pre/10-disable-cloudflare-mcp` reads a list of MCP server names
from a sibling config file (`~/clai.d/claude/pre/10-disable-cloudflare-mcp.conf`,
newline-separated) and, using `jq` with atomic tmpfile rename, ensures the
`~/.claude.json` project entry for `$CLAI_CWD` exists and has those names in
its `disabledMcpServers` array. Idempotent. Never removes names already
present.

If a project wants `cloudflare-graphql` enabled, drop a zero-byte
`<project>/clai.d/claude/pre/10-disable-cloudflare-mcp` to shadow the global
hook (and run `claude mcp` once to remove the server name from
`disabledMcpServers` for that project entry).

## Non-goals (for v1)

- No `env`-stage sourced hooks. No `wrap`-stage that takes over `exec`.
- No async or parallel hook execution.
- No hook deduplication across stages (a file in `pre/` and `post/` with the
  same name are unrelated).
- No support for hooks above `$HOME`.

## Dependencies

- `jq` (for the cloudflare hook's JSON edits — already on user's system).
- POSIX shell + standard utilities (`find`, `sort`, `realpath`/`readlink -f`).
- macOS: zsh + BSD utility flags per AGENT.md.
