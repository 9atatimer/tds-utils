# AGENT.md — tds-utils

It is very important you never do anything destructive to the git history.

It is very important that you enumerate the skills in prompts/ — but
conservatively. Don't read them all in; they'll flood your context.

Ingest the whole relevant file (and follow it) at the moment a task
starts that maps to one:
- Writing or reviewing tests → TESTING.md.
- About to push code, create or review a PR, reply to PR feedback, or
  subscribe to PR activity → GITHUB.md. The trigger is the push/review
  boundary, not just opening a PR — every interaction with the remote
  counts.

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
  filler. One or two sentences unless an explanation is requested; if more
  detail is wanted, it will be asked for.
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
- NEVER set a recurring/self-rearming trigger chain. One wake-up timer at
  most, then wait for the human. Never poll yourself -- it wastes quota.
- NEVER use interrogative choice-menu prompts. If you need something, ask
  directly for the missing value, with at most a one- or two-line suggestion.
- NEVER force-push. Land changes only via a PR off a fresh branch; if the
  designated branch is already merged, cut a new branch and open a new PR.

## Pull Request Review (do this WITHOUT being told)

- The moment ANY PR interaction starts -- opening, a review comment, CI, a
  reply -- ingest `prompts/GITHUB.md` and triage strictly against it. This
  is automatic; never wait to be told to check GITHUB.md.
- When you AGREE with review feedback and push a fix commit to the branch,
  you MUST kick off a Copilot re-review (`request_copilot_review` /
  `gh pr edit --add-reviewer @copilot`) so the next round fires.
- Reply to each comment and RESOLVE the thread as you address it; reject
  ones you disagree with, on the thread, with a concrete reason.
- Watch PRs via GitHub webhook EVENTS (the activity subscription), NEVER via
  self-scheduled triggers or polling.
