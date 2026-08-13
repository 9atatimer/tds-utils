#!/usr/bin/env bash
# SessionStart hook (committed, project scope): delegate to the session-start
# wrapper -- the per-session provisioning AUTHORITY
# (docs/design/SANDBOX-LIFECYCLE.DESIGN.md). The wrapper runs `lmde acquire`
# (refresh every fleet package to its current pin; fast no-op when current),
# then the offline configure-only `clai provision --copy --report`, then
# prints a version summary to stdout, which Claude Code adds to the session
# context. Laptop and cloud take the same path: acquire is fail-open, so a
# laptop without GH_AI_TOOLS_PAT degrades to configure-only with a warning.
#
# History: this hook used to carry its own npm install of ast-mcp (the
# pre-RD4 first-connect installer, then a remote-gated refresh) plus a
# separate clai-provision branch -- two install sites for one server
# (tds-utils#120), and a hook-local delivery path that duplicated what
# `lmde acquire` does behind the reviewed pins. All of that is now the
# wrapper's (and acquire's) job: the env-setup SEED wins the first-connect
# race from the snapshot, and the per-session acquire here keeps everything
# current from the next spawn on. One engine, one path, no bespoke installer.
#
# Fail-open: nothing here may block the session from starting.
set -uo pipefail

# --- Flow functions ---

run_hook() {
  local here wrapper
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || here=""
  wrapper="${here}/../../sandbox/claude-web/session-start.sh"
  if [ -n "${here}" ] && [ -f "${wrapper}" ]; then
    bash "${wrapper}" "$@"
    exit 0
  fi
  # Degraded fallback (wrapper missing -- should not happen in a checkout):
  # configure-only, same as the wrapper's own no-lmde path.
  echo "[.claude/hooks/session-start.sh] wrapper not found at ${wrapper} -- running configure-only fallback" >&2
  if command -v clai >/dev/null 2>&1; then
    clai provision --offline-ok || echo "[.claude/hooks/session-start.sh] clai provision failed (non-fatal)" >&2
  else
    echo "[.claude/hooks/session-start.sh] clai not on PATH -- skipping provisioning (fail-open)" >&2
  fi
  exit 0
}

# --- Main ---

main() {
  run_hook "$@"
}

main "$@"
