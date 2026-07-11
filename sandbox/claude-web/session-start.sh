#!/usr/bin/env bash
# session-start.sh -- Claude Code web/remote SessionStart hook wrapper: run
# configure-only `clai provision` against the clai that the env-setup stage
# already acquired. OFFLINE by design -- no bootstrap, no clone, no install.
#
# Provider hook contract (Claude Code web / remote sandboxes):
#   SessionStart hooks registered in .claude/settings.json run
#   synchronously BEFORE the agent loads .mcp.json and starts work, with
#   CLAUDE_PROJECT_DIR set to the repo checkout and CLAUDE_CODE_REMOTE=true
#   in cloud sandboxes.
#
# Acquisition already happened: the env-setup step (sandbox/claude-web/setup.sh)
# ran `lmde acquire` PRE-session and installed clai (onto PATH) + ast-mcp +
# the bundled skills/catalog from GitHub Packages. So this hook does NOT
# install anything and needs no network or token: it just runs clai's
# offline, configure-only provisioning engine (emit dialects, place skills,
# register ast-mcp at agent scope, print the epilogue). If clai is absent
# (env-setup did not run, or acquire failed), it skips -- fail-open.
#
# Install location (manual, by the human -- design non-goal to automate):
#   Register in <repo>/.claude/settings.json under hooks.SessionStart,
#   e.g. "command": "$CLAUDE_PROJECT_DIR/sandbox/claude-web/session-start.sh".
#   In tds-utils itself the laptop/self path is covered by
#   .claude/hooks/session-start.sh, whose clai-on-PATH branch runs the same
#   `clai provision`. This wrapper is the standalone configure-only form for
#   other repos whose env-setup stage runs `lmde acquire`.
#
# Fail-open: provisioning problems never block the session from starting.
set -uo pipefail

# --- Flow functions ---

# run_wrapper -- run clai's offline configure-only provisioning if clai is on
# PATH (placed there by the env-setup `lmde acquire`), else skip. Never blocks
# the session; always exits 0.
run_wrapper() {
  if command -v clai >/dev/null 2>&1; then
    clai provision --copy --report "$@" \
      || echo "[sandbox/claude-web/session-start.sh] clai provision failed (non-fatal)" >&2
  else
    echo "[sandbox/claude-web/session-start.sh] clai not on PATH (env-setup lmde acquire did not install it) -- skipping provisioning (fail-open)" >&2
  fi
  exit 0
}

# --- Main ---

main() {
  run_wrapper "$@"
}

main "$@"
