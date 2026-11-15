# AGENT.md -- tds-utils

It is very important you never do anything destructive to the git history.

Agent skills are provisioned into `.claude/skills/` (and the peer agent
dirs) by `clai provision` at session start. Load a skill's body the moment
a task enters its territory, and only that one; the `sdlc` skill carries
the always-in-effect laws. Two triggers are load-bearing enough to restate:
- Writing or reviewing tests -> the testing skill.
- About to push code, create or review a PR, reply to PR feedback, or
  subscribe to PR activity -> the github-workflow skill. Every interaction
  with the remote counts, not just opening a PR.

Repo-scoped radar data: `lmde/TECH_RADAR.md` (human-maintained -- audit
and propose, never edit without approval). A row is one line saying what
the tool is for, LMDE-wide; rationale goes in issues, `TODO_PLAN.md`, or a
skill.

## What This Project Is

Todd's universal unix environment/utility repo, pulled onto every new machine.
See README.tds for the original description.

## Workflow Rules

- **Always propose before writing.** Describe the approach, file placement, and
  design before producing code. Wait for approval.
- **Ask clarifying questions** about placement, naming, conventions, and scope
  before starting work.
- **Solve problems, don't work around them.** When a tool, command, or workflow
  produces broken output, diagnose the root cause and fix it. Do not silently
  switch to a different tool or manual approach to avoid the issue.
- The global rule to decide rather than ask does not relax these two:
  still propose before writing, and ask scope questions in prose.
- Never force-push. Land changes only via a PR off a fresh branch; if the
  designated branch is already merged, cut a new branch and open a new PR.
- Lessons live at the narrowest layer whose readers need them (sdlc skill,
  law 15): code comment (file-local) -> `docs/arch/` (component) -> this
  file (repo) -> shared skill (fleet). `TODO_PLAN.md`'s Lessons Learned
  holds only unsettled lessons on the work in progress.

## Platform & Shell

- Scripts must be **cross-platform** (Linux + macOS) unless inherently
  platform-specific.
- macOS scripts use **zsh** (`#!/bin/zsh`), not bash.
- macOS scripts must use **BSD tool syntax**, not GNU/Linux form.
  (e.g., `sed -i ''` not `sed -i`, `du -sm` is fine but watch for GNU-only flags.)
- Linux scripts use **bash** (`#!/usr/bin/env bash`).

## What is live: the release worktree

The dotfiles, `bin/` and emacs config here are the running configuration
of this machine, but they go live on a release, not on a save: `$HOME`
symlinks, `PATH` and `~/.tds/release` resolve into the `release` worktree
(`~/workplace/.worktrees/tds-utils-release`), never into this checkout.
`docs/ops/release-worktree.md` has the mechanics: the tiers, the public
and private units, `NO.RELEASE`, rollback, and how to test shell config
under `ZDOTDIR` and probe tmux without touching the live session.

- `bin/tds-release` is the install step: `-n` previews, no argument
  releases both units and pushes them. Merging to `master` deploys
  nothing. Run it only when the owner tells you to in the session.
- Never switch branches or edit inside the release worktree; whatever is
  in it is what the machine runs. `tds-release` refuses a dirty one.
- A file the machine writes at runtime (`~/.claude/settings.json`) is
  never symlinked out of the release worktree: give it a
  `clai.d/<agent>/pre/` hook that merges only the keys this repo owns.
- `clai.d/AGENT.global.md` (the core every agent loads) and
  `clai.d/<agent>/AGENT.<agent>.md` (one agent's fragment) are the
  machine's global agent instructions, not this file.
  `bin/agent-instructions` builds and links them at release
  (`docs/ops/clai.md`). Editing them is a PR like any other change.
  `test/smoketest_agent_budget.sh` fails when one agent's global file
  plus this file passes 32 KiB.
- Agent tooling (skills, `clai`, `ast-mcp`, `gadmin`) becomes current
  through `lmde acquire`, not `tds-release`: `docs/ops/provisioning-rail.md`.

## Repository Layout

```
bin/          Executable scripts (OS-neutral, language-dependent)
bash/         Bash configuration (dot.bashrc, dot.prompts, etc.)
macos/        macOS-specific dotfiles (dot.zshrc, dot.zprofile, etc.)
emacs/        Emacs configuration and elisp
git-config/   Git configuration (dot.gitconfig, dot.gitignore_global)
git-aliases/  Git alias definitions
git-hooks/    Git hooks (pre-push, etc.)
local/        Machine-specific customizations
third-party/  Vendored external tools
```

- New executable scripts go in **bin/**. `bin/tmux_logging.sh` and
  `bin/tmux_shepherd.sh` are log-hoarder's tmux hook scripts
  (`docs/design/LOG-HOARDER.DESIGN.md`), not session-management tools;
  the session tool is `bin/tmux-herd` (`docs/design/TMUX-HERD.DESIGN.md`).
  Grep `bin/` and `docs/design/` for the concept before naming a new one.
- macOS-only config goes in **macos/**.
- Dotfile configs use the **dot.** prefix convention (e.g., `dot.zshrc`).
- This repo is public (`PUBLIC.REPO`). Naming tds-internal is fine; its
  contents are not -- no account ids, 1Password item or vault names,
  buckets, gateway paths, trigger ids. The pre-commit bleed guard refuses
  denylisted strings (`docs/bleed-guard.md`); prose that describes private
  contents is on you.

## Code Architecture

- Use **domain-driven / hexagonal / clean architecture** principles. Separate concerns: I/O,
  logic, and glue are distinct.
- Use **TDD/BDD**: write tests first after design, then implement against them.
  This ensures code is testable by construction.
- The repo has a `test/` convention (per README.tds). Tests go there.

## Shell Script Structure

All shell scripts must follow a **function-based** structure:

- **Action functions**: do one thing (query TM exclusions, compute a size, etc.)
- **Flow functions**: contain logic/control flow, call action functions.
- **Main block**: parses flags/arguments only, then calls the top-level flow function.
- No loose logic outside of functions (aside from the main argument-parsing block).

Example skeleton:

```zsh
#!/bin/zsh
# script-name -- one-line description

set -euo pipefail

# --- Action functions ---
get_thing() { ... }
check_thing() { ... }

# --- Flow functions ---
run_audit() {
    local things
    things=$(get_thing)
    check_thing "$things"
}

# --- Main ---
main() {
    local flag_verbose=false
    while getopts "vh" opt; do
        case "$opt" in
            v) flag_verbose=true ;;
            h) usage; exit 0 ;;
            *) usage; exit 1 ;;
        esac
    done
    run_audit "$flag_verbose"
}

main "$@"
```

## Style

- Header comment: shebang, script name, one-line purpose.
- `set -euo pipefail` at the top.
- Functions grouped and labeled with section comments (`# --- Section ---`).
- Use `local` for all function-scoped variables.
- Cleanup that must run (a temp dir holding a credential, a child to
  stop) traps the signals by name: `trap cleanup EXIT INT TERM HUP`. In
  zsh an `EXIT` trap alone does not run when the script is killed by
  SIGTERM -- not at top level, not inside a function (verified, zsh 5.9,
  2026-09-25: a spike runner left a registry credential on disk after
  `kill -TERM`). Only the named signal traps fire.

## Landing, review and CI

- This repo lands PRs through tedium: `gate` (the `dist-ci.yml` job that
  needs every other job) must be green on the PR head and on tedium's
  staging commit, and a code owner's approval is required on every PR.
  `review-settled` is off (always green). `docs/ops/tedium.md` has the
  rules, the `hold` label and `tedium dryrun`.
- A new CI job goes into `gate`'s `needs`, with `needs: changes` and a
  scope in `.github/scripts/changed-scopes.sh`. Never a `paths:` filter:
  a workflow that does not run never reports `gate`.
- A tedium landing does not close issues: close them by hand with a
  comment naming the PR.
- `adherence-judge` gates changes to `adherence/`, `adherence.toml`, the
  two Adherence records and the radar. Read `docs/ops/adherence.md`
  before running `bin/adhere` locally or answering a verdict.
- The moment any PR interaction starts, load the github-workflow skill.
  This repo carries the `/ocr` caller. Watch PRs through GitHub events,
  never by polling.

## Infrastructure

This repo owns no long-lived cloud resource; the fleet's Terraform lives
in tds-internal `ops/terraform/`, whose `docs/policy/` files are the
rules. Load the `iac` skill the moment a task touches a cloud resource or
a GitHub secret. `docs/ops/infrastructure.md` covers the two things here
that look like infrastructure (`ops/terraform/remvllm/`, `lmde/`) and the
secret names this repo's workflows read.
