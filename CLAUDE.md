# CLAUDE.md — tds-utils

## What This Is

Todd's universal unix environment/utility repo, pulled onto every new machine.
See README.tds for the original description.

## Workflow Rules

- **Always propose before writing.** Describe the approach, file placement, and
  design before producing code. Wait for approval.
- **Ask clarifying questions** about placement, naming, conventions, and scope
  before starting work.

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

- Use **hexagonal / clean architecture** principles. Separate concerns: I/O,
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
