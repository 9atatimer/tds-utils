#!/usr/bin/env bash
# session-start.sh -- Claude Code web/remote SessionStart hook wrapper:
# bootstrap pinned clai (if needed) and run `clai provision`.
#
# Provider hook contract (Claude Code web / remote sandboxes):
#   SessionStart hooks registered in .claude/settings.json run
#   synchronously BEFORE the agent loads .mcp.json and starts work, with
#   CLAUDE_PROJECT_DIR set to the repo checkout and CLAUDE_CODE_REMOTE=true
#   in cloud sandboxes. Network is available at session start; brokered
#   GH_TOKEN does NOT work against api.github.com, so GH_AI_TOOLS_PAT must
#   be configured as a sandbox secret (same requirement as the ast-mcp
#   hook).
#
# Install location (manual, by the human -- design non-goal to automate):
#   Register in <repo>/.claude/settings.json under hooks.SessionStart,
#   e.g. "command": "$CLAUDE_PROJECT_DIR/sandbox/claude-web/session-start.sh".
#   In tds-utils itself this path is already covered: the existing
#   .claude/hooks/session-start.sh implements the issue #84 three-way
#   branch -- `clai provision --offline-ok` when clai is on PATH, and the
#   full pinned bootstrap via sandbox/provision.sh when
#   CLAUDE_CODE_REMOTE=true and clai is absent. This wrapper is the
#   standalone form for other repos that want the full bootstrap.
#
# Fail-open: provisioning problems never block the session from starting.
set -uo pipefail

# --- Flow functions ---

# find_core -- provision.sh sibling-relative to this file when the whole
# sandbox/ tree is present; else via CLAUDE_PROJECT_DIR (covers this file
# being copied into .claude/hooks/ while sandbox/ stays at the repo root).
find_core() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
  if [ -f "$here/../provision.sh" ]; then
    printf '%s\n' "$here/../provision.sh"
  elif [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -f "$CLAUDE_PROJECT_DIR/sandbox/provision.sh" ]; then
    printf '%s\n' "$CLAUDE_PROJECT_DIR/sandbox/provision.sh"
  else
    return 1
  fi
}

run_wrapper() {
  local core
  if ! core="$(find_core)"; then
    echo "[sandbox/claude-web/session-start.sh] sandbox/provision.sh not found (looked next to this script and under \${CLAUDE_PROJECT_DIR}) -- skipping provisioning (fail-open)" >&2
    exit 0
  fi
  bash "$core" "$@" || echo "[sandbox/claude-web/session-start.sh] provision.sh failed (non-fatal)" >&2
  exit 0
}

# --- Main ---

main() {
  run_wrapper "$@"
}

main "$@"
