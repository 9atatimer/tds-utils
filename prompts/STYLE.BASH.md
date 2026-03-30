# Bash Style Guide for Coding Agents

Follow these instructions whenever you create or edit Bash scripts in this repository.

## General Expectations
- Assume Bash 5.2+ (Homebrew build) and use the shebang `#!/usr/bin/env bash`
- Enable strict mode at the top of each script: `set -euo pipefail`

## Required Script Layout
Structure every script in five clear sections:
1. **Header** — Shebang and a comment block describing purpose, usage, prerequisites, and side effects
2. **Shared Libraries** — `source` statements for shared helpers (if any)
3. **Helper Functions** — One function per logical operation, short and single-purpose
4. **Main Orchestrator** — A `main()` function that sequences the helpers
5. **Execution Guard** — `main "$@"` at the end of the file

## Helper Function Guidelines
- Declare function-local variables with `local`
- Quote all parameter expansions (`"${variable}"`)
- Prefer early returns over deeply nested conditionals
- **Avoid IFS**: Never reassign global IFS
- Use `readarray -t ARR < <(command)` for multi-line array assignment
- Prefer `< <(command)` over `|` (pipe) to prevent subshell variable loss
- Favor descriptive logging inside helpers so the script reads like a narrative when run

## Error Handling and Messaging
- Use structured error messages that tell a human what went wrong and what to check next
- Let `main` exit on the first failure by propagating non-zero statuses (`set -e`)
- Provide actionable error messages

## Testing and Verification
- Document in commit messages whether scripts were executed or only statically inspected
- When possible, add lightweight validation helpers (e.g., verifying required commands exist via `command -v`)
