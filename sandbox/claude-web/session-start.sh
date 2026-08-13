#!/usr/bin/env bash
# session-start.sh -- Claude Code web/remote SessionStart hook wrapper: the
# per-session provisioning AUTHORITY (SANDBOX-LIFECYCLE.DESIGN.md). Runs
# `lmde acquire` (refresh every fleet package to its current pin; fast no-op
# when current) and THEN the offline, configure-only `clai provision`, and
# prints a short version summary to stdout, which Claude Code adds to the
# session context.
#
# Provider hook contract (Claude Code web / remote sandboxes):
#   SessionStart hooks registered in .claude/settings.json run
#   synchronously BEFORE the agent loads .mcp.json and starts work, with
#   CLAUDE_PROJECT_DIR set to the repo checkout and CLAUDE_CODE_REMOTE=true
#   in cloud sandboxes. They run EVERY session (startup and resume) -- unlike
#   the environment setup script, which runs once per snapshot-cache build
#   (~7 days) and is only the CACHE SEEDER.
#
# Why acquire runs HERE and not (only) at env-setup: the setup script's work
# is frozen into the environment snapshot, so everything it installed --
# packages and pins alike -- goes stale for the cache lifetime. The session
# has GH_AI_TOOLS_PAT and authed reach to npm.pkg.github.com (measured,
# 2026-08-13), so the per-session acquire is what actually delivers current
# skills and pinned executables. MCP-server binaries refreshed here apply on
# the NEXT spawn (first connect races this hook -- RD4); the seed copy in the
# snapshot serves the current session.
#
# Pins (D1): no --pins is passed when the fleet pins exist inside the
# acquired skills payload -- the acquire engine resolves them itself, and a
# wrapper-passed file would wrongly outrank them. When the fleet pins are
# absent (first run before any skills payload landed), the checkout's legacy
# sandbox/pins.env is passed as the transition fallback so the first acquire
# is still gated.
#
# Install location (manual, by the human -- design non-goal to automate):
#   Register in <repo>/.claude/settings.json under hooks.SessionStart,
#   e.g. "command": "$CLAUDE_PROJECT_DIR/sandbox/claude-web/session-start.sh".
#   In tds-utils itself the committed .claude/hooks/session-start.sh runs the
#   same acquire-then-provision; repos that are not tds-utils use the
#   naatm-sandbox package's session-start bin instead (it vendors the acquire
#   engine).
#
# Fail-open: provisioning problems never block the session from starting.
set -uo pipefail

# The fleet pins convention path (must match lmde/lib/acquire.sh
# ACQUIRE_FLEET_PINS; SANDBOX-LIFECYCLE.DESIGN.md D1).
FLEET_PINS="${HOME}/.local/lib/node_modules/@nine-at-a-time-media/skills/pins.env"

# Where acquire records installed versions (must match acquire.sh
# ACQUIRE_STATE_DIR); the summary reads the stamps, never invokes binaries.
ACQUIRE_STATE_DIR="${HOME}/.local/state/tds-utils/acquire"

# --- Action functions ---

note() { echo "[sandbox/claude-web/session-start.sh] $*" >&2; }

# find_lmde -- echo the lmde to run: the checkout-relative bin/lmde (this
# script lives at sandbox/claude-web/ inside the tds-utils checkout), else an
# lmde on PATH, else nothing (return 1; the caller degrades fail-open).
find_lmde() {
  local here candidate
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || here=""
  if [ -n "${here}" ]; then
    candidate="${here}/../../bin/lmde"
    if [ -f "${candidate}" ]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  fi
  if command -v lmde >/dev/null 2>&1; then
    command -v lmde
    return 0
  fi
  return 1
}

# legacy_pins -- echo the checkout's sandbox/pins.env when present (the
# pre-fleet transition fallback), else nothing.
legacy_pins() {
  local here candidate
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || return 1
  candidate="${here}/../pins.env"
  [ -f "${candidate}" ] || return 1
  # Normalize away the /../ for a readable argv in logs and tests.
  ( cd "$(dirname "${candidate}")" && printf '%s/%s\n' "$(pwd -P)" "$(basename "${candidate}")" )
}

# run_acquire -- refresh the fleet packages. Fail-open on every path: a
# missing lmde, missing PAT, or unreachable registry degrades to whatever the
# snapshot seeded, with acquire's own warnings naming what is stale.
run_acquire() {
  local lmde pins
  if ! lmde="$(find_lmde)"; then
    note "lmde not found (no checkout-relative bin/lmde, none on PATH) -- skipping acquire; running configure-only (fail-open)"
    return 0
  fi
  if [ -f "${FLEET_PINS}" ]; then
    bash "${lmde}" acquire \
      || note "lmde acquire failed (non-fatal)"
  elif pins="$(legacy_pins)"; then
    bash "${lmde}" acquire --pins "${pins}" \
      || note "lmde acquire failed (non-fatal)"
  else
    bash "${lmde}" acquire \
      || note "lmde acquire failed (non-fatal)"
  fi
  return 0
}

# print_summary -- one short stdout block naming the stamped versions (and the
# skills stamp when present). stdout of a SessionStart hook is added to the
# session context, so keep it tight: this is how an agent knows which tooling
# versions it is actually running (template-tools#381).
print_summary() {
  local f shortname version line=""
  if [ -d "${ACQUIRE_STATE_DIR}" ]; then
    for f in "${ACQUIRE_STATE_DIR}"/*.version; do
      [ -f "${f}" ] || continue
      shortname="$(basename "${f}" .version)"
      version="$(head -n1 "${f}" 2>/dev/null)" || version=""
      [ -n "${version}" ] || continue
      line="${line}${line:+, }${shortname} ${version}"
    done
  fi
  if [ -n "${line}" ]; then
    echo "Provisioned tooling (acquire stamps): ${line}."
  else
    echo "Provisioned tooling: no acquire stamps found -- acquisition has not run; tooling may be missing or stale."
  fi
  return 0
}

# --- Flow functions ---

# run_wrapper -- acquire (refresh), then clai's offline configure-only
# provisioning if clai is on PATH, then the stdout summary. Never blocks the
# session; always exits 0.
run_wrapper() {
  run_acquire
  if command -v clai >/dev/null 2>&1; then
    clai provision --copy --report "$@" \
      || note "clai provision failed (non-fatal)"
  else
    note "clai not on PATH (acquire did not install it) -- skipping provisioning (fail-open)"
  fi
  print_summary
  exit 0
}

# --- Main ---

main() {
  run_wrapper "$@"
}

main "$@"
