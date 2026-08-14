#!/usr/bin/env bash
# SessionStart hook shim (committed, project scope) -- this repo's REDUNDANT
# per-session provisioning carrier. Not the primary one; see below.
#
# WHY THIS FILE EXISTS. The PRIMARY carrier is the user-scope hook that
# `naatm-sandbox setup` writes into the container at
# ~/.claude/hooks/naatm-session-start.sh (#124, corrected 2026-08-13: those
# DO fire in cloud, and they are the only carrier that covers multi-repo
# sessions, whose project dir is the checkouts' parent). This committed shim
# is deliberate REDUNDANCY -- it covers laptops and any environment whose
# setup stage never ran naatm-sandbox. Both run the same idempotent engine,
# so a double-fire is a fast no-op.
#
# It is also deliberately LOW-VELOCITY: find the engine, run it, fail open.
# All behavioral churn lives behind the acquired packages
# (docs/design/SANDBOX-LIFECYCLE.DESIGN.md, D3); this file should almost
# never change.
#
# History: this hook used to delegate to sandbox/claude-web/session-start.sh,
# a repo-local reimplementation of the same authority. That wrapper was
# retired (#126) -- it had DIVERGED from the packaged engine, provisioning
# only its cwd where the packaged bin provisions the cwd when it is a
# checkout, else every immediate child checkout (template-tools#417). Two
# implementations of one authority is the divergence D2 warns about; this
# now calls the packaged bin directly.
#
# NOTE ON MCP BINARIES. This hook cannot be the install point for an
# MCP-server binary. Claude Code starts the .mcp.json connect BEFORE this
# process spawns (measured 2026-08-14, #225: ~600 ms ahead, completing ~7 s
# before the hook returns), so first connect is served by whatever the
# environment-setup SEED left on disk. The acquire here refreshes it for the
# NEXT spawn -- the accepted N-1 window (PROVISION.DESIGN.md RD4).
#
# What it runs, in preference order:
#   1. naatm-sandbox-session-start (from @nine-at-a-time-media/sandbox --
#      the per-session AUTHORITY: acquire refresh to the fleet pins, then
#      offline `clai provision`, then a stdout version summary that Claude
#      Code adds to the session context);
#   2. bare `clai provision --copy --report` (configure-only degrade);
#   3. nothing, loudly (fail-open -- a missing engine never blocks the
#      session).
set -uo pipefail

# --- Action functions ---

note() { echo "[.claude/hooks/session-start.sh] $*" >&2; }

# Both finders prefer the PINNED user-scope install (~/.local/bin -- what the
# setup stage persisted) over whatever PATH resolves, so an ambient
# same-named binary cannot shadow the pinned one; PATH is the fallback.
# ${HOME:-} guarding keeps `set -u` from aborting the hook if HOME is somehow
# unset -- this script must never block a session.

# find_engine -- the session-start authority bin.
find_engine() {
  if [ -n "${HOME:-}" ] && [ -x "${HOME}/.local/bin/naatm-sandbox-session-start" ]; then
    printf '%s\n' "${HOME}/.local/bin/naatm-sandbox-session-start"
    return 0
  fi
  if command -v naatm-sandbox-session-start >/dev/null 2>&1; then
    command -v naatm-sandbox-session-start
    return 0
  fi
  return 1
}

# find_clai -- fallback configure-only path.
find_clai() {
  if [ -n "${HOME:-}" ] && [ -x "${HOME}/.local/bin/clai" ]; then
    printf '%s\n' "${HOME}/.local/bin/clai"
    return 0
  fi
  if command -v clai >/dev/null 2>&1; then
    command -v clai
    return 0
  fi
  return 1
}

# --- Flow functions ---

run_hook() {
  local engine clai
  if engine="$(find_engine)"; then
    # Execute directly, not via `bash` -- find_engine returns an executable
    # whose interpreter is its own business (today a bash script, but the npm
    # bin contract only promises an executable).
    "$engine" || note "naatm-sandbox-session-start failed (non-fatal)"
    exit 0
  fi
  if clai="$(find_clai)"; then
    note "naatm-sandbox-session-start not found -- configure-only degrade"
    "$clai" provision --copy --report || note "clai provision failed (non-fatal)"
    exit 0
  fi
  note "no provisioning engine found (naatm-sandbox-session-start and clai both absent) -- session starts unprovisioned (fail-open)"
  exit 0
}

# --- Main ---

main() {
  run_hook "$@"
}

main "$@"
