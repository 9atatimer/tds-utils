# chores -- laptop-local herd of LLM-adjacent scheduled jobs

Design record: `docs/design/CHORES.DESIGN.md` (APPROVED). Concept:
`docs/concepts/lmde-tasks/`.

## Try it

```zsh
export CHORES_HOME=~/workplace/tds-internal/ops/chores   # your git-tracked definitions
chores validate                 # every definition, backend and ceiling binding
chores run daily-local-smoke --dry-run
chores run daily-local-smoke    # admission still applies (PAUSED, ceilings, breaker)
chores status                   # or --json; chores ui for the TUI
chores install                  # launchd agent (macOS) / systemd user timer (Linux)
```

`chores install` also remembers that `CHORES_HOME` in the state dir
(`<state>/home`), and the generated launchd/systemd unit carries it too.
Every later entry point that sees no shell export -- the tick, the
menu-bar monitor, a Dock launch -- resolves the same herd; an explicit
`CHORES_HOME` in the environment still wins. `chores uninstall` forgets it.

State lives in `$XDG_STATE_HOME/chores` (default `~/.local/state/chores`).
A customised `XDG_STATE_HOME` belongs in `~/.zshenv` (the three-file
contract in the repo AGENT.md): every launchd job here runs through zsh,
which sources `.zshenv` unconditionally, so the menu-bar monitor and the
Dock launcher see the same state root as your shell and find the herd
pointer there. The tick unit carries the value explicitly as well.
State holds:
one directory per run (`run.json`, `definition.md`, `transcript.jsonl`,
`stdout.log`, `stderr.log`, `errors.log`), the append-only
`ledger.ndjson`, `notifications.ndjson`, the `PAUSED` sentry and
`last_tick`.

## Layout

```
src/chores/
  domain/        pure values and policies: Schedule, Chore, Budget, RunRecord,
                 due / admission / spend / ceiling / breaker / redaction
  ports/         the seams as Protocols: completion, agent, process, store,
                 clock, power, network, secrets, notifier, definitions, catalog
  adapters/      mechanisms: ollama, openai-compat (the AI Gateway), claude-cli,
                 filesystem store, subprocess, op read, launchd/systemd, host
  application/   use cases over ports only: run, tick, status and controls
  cli/           click entry point, renderers, the composition root (wiring)
  tui/           the Textual dashboard (optional extra `tui`)
tests/unit/      fakes for every port; contract tests pin fakes to adapters
tests/integration/  real subprocesses and git
```

## Develop

```zsh
cd chores
uv sync --all-extras
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Surfaces outside this package: `bin/chores` (launcher), `bin/chores-monitor`
(rumps menu bar), `bin/chores-dashboard` (opens the TUI in Terminal),
`macos/apps/chores/` (Dock tile), `macos/launchd/com.tds.chores-monitor.plist`,
`packages/chores.pkg`.
