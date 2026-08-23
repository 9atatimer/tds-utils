# AGENT.md — tds-utils

It is very important you never do anything destructive to the git history.

Agent skills are provisioned into `.claude/skills/` (and the peer agent
dirs) from the canonical `template-tools/skills/` tree by `clai provision`
at session start; the flat `prompts/` channel is retired (issue #179).
Skill descriptions surface lazily -- load a skill's body the moment a task
enters its territory, and only that one. The `sdlc` skill carries the
always-in-effect laws and the station-to-station reading order.

Two triggers are load-bearing enough to restate here:
- Writing or reviewing tests -> the testing skill.
- About to push code, create or review a PR, reply to PR feedback, or
  subscribe to PR activity -> the github-workflow skill. The trigger is
  the push/review boundary, not just opening a PR -- every interaction
  with the remote counts.

Repo-scoped radar data: `lmde/TECH_RADAR.md` (human-maintained -- audit
and propose, never edit without approval). The provisioned tech-radar
skill carries the fleet defaults and points here for LMDE specifics.

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

## Platform & Shell

- Scripts must be **cross-platform** (Linux + macOS) unless inherently
  platform-specific.
- macOS scripts use **zsh** (`#!/bin/zsh`), not bash.
- macOS scripts must use **BSD tool syntax**, not GNU/Linux form.
  (e.g., `sed -i ''` not `sed -i`, `du -sm` is fine but watch for GNU-only flags.)
- Linux scripts use **bash** (`#!/usr/bin/env bash`).

## The Release Worktree -- What Is Live, and What Is Not

**The dotfiles in this repo are the running configuration of the machine you
are on -- but they go live on a release, not on a save.** `$HOME` symlinks do
not resolve into this checkout. They resolve into the `release` worktree:

```
~/.zshrc  -> ~/workplace/.worktrees/tds-utils-release/macos/dot.zshrc
~/.emacs.d -> ~/workplace/.worktrees/tds-utils-release/emacs/dot.emacs.d
~/.claude/CLAUDE.md -> ~/workplace/.worktrees/tds-utils-release/clai.d/AGENT.global.md
```

`bin/tds-release-link` owns those links (`-n` to preview, `-r` to put them back
on the primary checkout). Run it after creating the release worktree on a new
machine; it is idempotent, and it only ever moves symlinks that already point
into one of the two checkouts.

It also maintains one pointer that is not a dotfile:

```
~/.tds/release -> ~/workplace/.worktrees/tds-utils-release
```

`PATH` and the two `dot.zshrc` source fallbacks key off that path rather than
naming the worktree, because the startup files must also work on a machine that
has no release worktree at all. Tier order, highest that exists wins:

| tier | path | owner |
|------|------|-------|
| 1 | `~/.tds/dist/current` | `bin/tds-install` -- a real dist install |
| 2 | `~/.tds/release` | `bin/tds-release-link` -- the release worktree |
| 3 | `~/workplace/tds-utils` | nobody; fresh-clone fallback, live-editable |

Tier 3 ranks last precisely because it is the one that changes under you.
`tds_path_apply` filters entries by `-d`, so a missing tier simply drops out
and a fresh clone still gets a working shell (issues #202, #235).

### Three branches, three roles

| where | branch | what it is |
|-------|--------|------------|
| `~/workplace/tds-utils` | `master` | the primary checkout: read, review, never live |
| `~/workplace/.worktrees/tds-utils-release` | `release` | what the machine is actually running |
| `~/workplace/.worktrees/tds-utils-<topic>` | `<topic>` | where you do the work |

`release` is fast-forward only and is never committed to directly. It is
always an exact commit of `master` that went through a PR -- so "what is
running" is a point on the reviewed history, never a divergent head and never
a half-finished edit.

### Releasing

```zsh
bin/tds-release -n          # what would go live, and which commits
bin/tds-release             # fast-forward release to origin/master, push it
bin/tds-release <sha>       # release a specific reviewed commit
bin/tds-release -f <sha>    # roll back (rewind release deliberately)
```

That IS the install step for this machine. The moment `release` moves, the new
config is what every new shell, editor, and agent session loads. Nothing else
runs.

Three refusals are worth knowing before you hit them:

- **A commit carrying `NO.RELEASE` is never released.** Everything on `master`
  is releasable by default -- that is the whole point of the branch -- so a
  commit that landed but is not yet fit to go live has to say so. Put the
  reason in the file; `tds-release` prints it back at whoever hits the refusal:

  ```zsh
  echo "held: the ledger migration must be run by hand first" > NO.RELEASE
  ```

  There is deliberately no override. `-f` rewinds; it does not release held
  work. The way past a sentry is to remove it on `master` and release that
  commit, which leaves the decision in the history where it can be reviewed
  rather than in someone's shell.

- **The target must be an ancestor of `origin/master`.** A topic commit can be
  a perfectly clean fast-forward from `release` and still have skipped review,
  so "fast-forwardable" is not the test -- "on reviewed history" is. `-f` lifts
  the fast-forward requirement only; it does not lift this one. Merge it first.
- **The release worktree must be clean**, and that is checked before the
  already-current shortcut. A dirty release tree is a live-config problem
  whether or not `HEAD` happens to sit on the commit you asked for, so
  `tds-release` reports it rather than saying "up to date" over the top of it.

### What this buys, and the one trap left

Two hazards this arrangement removes, both of which used to bite hard:

- **`git checkout <branch>` in the primary checkout no longer rewrites the
  running shell config mid-session.** It used to: a branch predating a
  `.zshenv` fix silently reinstated the bug in every shell spawned from that
  moment on, including agent tool calls, and the failure surfaced later
  somewhere unrelated.
- **Editing `macos/dot.*` no longer takes effect immediately.** A half-finished
  edit is now just an edit.

The trap that remains: **never switch branches or edit inside the release
worktree.** It is the one checkout where the old rules still apply in full --
whatever is in it is what the machine is running right now. `bin/tds-release`
refuses to release into a dirty tree for exactly this reason.

Do topic work in its own worktree, per the global rule that worktrees live in
`~/workplace/.worktrees/<repo>-<topic>`:

```zsh
git worktree add ~/workplace/.worktrees/tds-utils-<topic> -b <branch> master
# then edit via: git -C ~/workplace/.worktrees/tds-utils-<topic> ...
```

### The global agent instruction file

`clai.d/AGENT.global.md` is the global instruction file for every agent on this
machine (Claude Code, codex, opencode, gemini), reaching them through the
release worktree. It is NOT this file: `AGENT.md` is repo-scoped instructions
for working in tds-utils, `AGENT.global.md` is machine-scoped instructions that
happen to be version-controlled here.

It carries the `.global` suffix so that an agent working inside `clai.d/` does
not auto-load it a second time as directory-scoped instructions.

Editing it is a PR like any other change -- which is the point. Before this it
was an untracked file in `~/.claude/`, edited in place with no review, no
history, and no way for a second machine to have the same one.

To TEST candidate shell config without installing it, point `ZDOTDIR` at a
staging directory under `env -i`. That sources your candidates while
`/etc/zshenv` and `/etc/zprofile` still run, so macOS `path_helper` stays in
the loop -- which is exactly where the interesting bugs live:

```zsh
stage=$(mktemp -d)
cp macos/dot.zshenv "$stage/.zshenv"
cp macos/dot.zprofile "$stage/.zprofile"
cp macos/dot.zshrc "$stage/.zshrc"

# .zshenv + .zprofile only -- .zshrc is NOT sourced by a non-interactive shell
env -i HOME="$HOME" ZDOTDIR="$stage" TERM=dumb /bin/zsh -lc 'command -v bash'

# adds .zshrc; TMUX must be non-empty or .zshrc execs tmux and the probe hangs
env -i HOME="$HOME" ZDOTDIR="$stage" TERM=dumb TMUX=probe /bin/zsh -lic \
    'command -v bash' </dev/null
```

Match the shell shape to the file you are testing -- zsh sources a different
set for each, and a green result from the wrong shape means nothing:

| invocation | `.zshenv` | `.zprofile` | `.zshrc` |
|------------|-----------|-------------|----------|
| `zsh -c`   | yes       | no          | no       |
| `zsh -lc`  | yes       | yes         | no       |
| `zsh -ic`  | yes       | no          | yes      |
| `zsh -lic` | yes       | yes         | yes      |

Stage all three files regardless. An empty `ZDOTDIR` is not a neutral control
-- it means no dotfiles load at all, so you measure bare `path_helper` output
and conclude the config is broken when you never loaded it.

See `test/smoketest_shell_env.sh` for the worked version, and issue #176 for
what it cost to find this out.

Note that `CLAUDE.md` is itself a symlink to `AGENT.md` -- edit `AGENT.md`.

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

- New executable scripts go in **bin/**.
- macOS-only config goes in **macos/**.
- Dotfile configs use the **dot.** prefix convention (e.g., `dot.zshrc`).

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
# script-name — one-line description

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

## Agent Operating Rules

- Keep answers succinct and terse. Specificity is a virtue. No expository
  filler. Stay on task. One or two sentences unless an explanation is
  requested; if more detail is wanted, it will be asked for.
- Do not volunteer generic/unprompted starting or onboarding advice; assume
  you are stepping into a problem already in progress. This does NOT relax
  the Workflow Rules above -- still propose before writing and ask clarifying
  scope questions.
- Always review the repo's CLAUDE.md/AGENT.md instructions.
- In an ephemeral/sandboxed runtime the bash tool is a throwaway Docker
  sandbox -- use it freely for self-computation there. Do NOT assume that
  everywhere: on a real checkout (e.g. a laptop) bash affects the real disk
  and network, so assume side effects unless you have confirmed you are in
  the sandbox.
- NEVER pull down and run a shell script (e.g. `curl ... | sh`). Install
  software only through package managers that verify signed code.
- NEVER set a timer, wakeup, or scheduled trigger to wake yourself up -- not
  a single one, and never a recurring chain. Do the work now, then stop and
  wait for the human to notify you. Never poll yourself -- it wastes quota.
  The sole exception is a schedule the human starts explicitly (e.g. `/loop`):
  honor exactly what was asked for and add no timers of your own on top.
- Markdown is ASCII only. Use `--` not an em-dash, `->` and `<-` not arrow
  glyphs, `...` not an ellipsis, straight quotes, and ASCII box-drawing
  (`+ - |`) in diagrams. Never emit Unicode punctuation or symbols in a `.md`
  file. Applies to newly written or edited prose; it does not mandate churning
  untouched existing content.
- When told to swarm-code a solution (e.g. `ultracode`), automatically open a
  PR when the coding concludes -- do not wait to be asked -- then automatically
  triage Copilot's review feedback per the github-workflow skill.
- NEVER use interrogative prompts. Not choice menus, not "shall I proceed?",
  not "which do you prefer?". Decide, state the decision and its reason in one
  line, and act. Only ask when the answer is a value you cannot obtain or
  derive (a credential, a name, a URL) -- then ask for that value directly.
- NEVER force-push. Land changes only via a PR off a fresh branch; if the
  designated branch is already merged, cut a new branch and open a new PR.
- Lessons live at the narrowest layer whose readers need them (sdlc skill,
  law 15): code comment (file-local) -> `docs/arch/` (component) -> this
  file (repo) -> shared skill (fleet). `TODO_PLAN.md`'s Lessons Learned
  holds only unsettled lessons on the work in progress; issues never hold
  lessons -- they vanish when the root cause is fixed.

## Pull Request Review (do this WITHOUT being told)

- The moment ANY PR interaction starts -- opening, a review comment, CI, a
  reply -- ingest the github-workflow skill and triage strictly against
  it. This is automatic; never wait to be told to load it.
- When you AGREE with review feedback and push a fix commit to the branch,
  you MUST kick off a Copilot re-review (`request_copilot_review` /
  `gh pr edit --add-reviewer @copilot`) so the next round fires.
- Reply to each comment and RESOLVE the thread as you address it; reject
  ones you disagree with, on the thread, with a concrete reason.
- Watch PRs via GitHub webhook EVENTS (the activity subscription), NEVER via
  self-scheduled triggers or polling.
