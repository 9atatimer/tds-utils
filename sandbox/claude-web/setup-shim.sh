#!/usr/bin/env bash
# setup-shim.sh -- PASTE THIS (and only this) into the Claude Code web
# Environment "Setup script" box. Everything else lives in git.
#
# Why a shim. The web setup stage receives NO GH_*/GITHUB_* environment
# variables -- only CLAUDE_* (measured; issue #111). The session gets them, this
# stage does not. So the credential has to arrive in the pasted text. Keeping
# the pasted text to a credential plus an exec means the real logic
# (sandbox/claude-web/setup.sh) stays versioned, reviewed, and testable, and
# this box never needs re-pasting when that script changes.
#
# What the PAT must be: a CLASSIC personal access token carrying `read:packages`
# (RD2). Fine-grained tokens have no Packages permission. Delivery is the
# GitHub Packages npm registry; measured from this stage: 401 unauthenticated,
# 200 with a correct classic PAT.
#
# Exposure. This is no worse than the Environment-variables box, whose own UI
# warns it is "visible to anyone using this environment", and is meaningfully
# better in one respect: a token here is NOT injected into the session
# environment, so the agent, its subagents, and anything that talks a prompt
# injection into running `env` cannot read it.
#
# DO NOT add `set -x` -- it would echo the PAT. DO NOT add logic here; add it to
# setup.sh. DO NOT commit a real token to this file.
set -uo pipefail

# --- Configuration (the only thing that ever changes in this box) ---

PAT='PASTE-CLASSIC-read:packages-PAT-HERE'

# --- Action functions ---

log() { printf '[tds shim] %s\n' "$*" >&2; }

# is_checkout <dir> -- three markers, so an unrelated repo cloned side by side
# can never be mistaken for ours. Handing the PAT to a stray directory's script
# would be the worst possible outcome of a wrong guess.
is_checkout() {
  [ -n "${1:-}" ] \
    && [ -f "$1/sandbox/claude-web/setup.sh" ] \
    && [ -f "$1/sandbox/provision.sh" ] \
    && [ -f "$1/.mcp.json" ]
}

# find_checkouts -- every validating candidate, deduped, one per line.
find_checkouts() {
  local c r hits=""
  for c in "${CLAUDE_PROJECT_DIR:-/nonexistent}" "$PWD"/* /home/*/* "$HOME"/*; do
    is_checkout "$c" || continue
    r="$(cd "$c" 2>/dev/null && pwd -P)" || continue
    hits="$hits$r
"
  done
  printf '%s' "$hits" | grep . | sort -u
}

# --- Flow functions ---

run_shim() {
  local hits count target
  hits="$(find_checkouts)"
  count="$(printf '%s\n' "$hits" | grep -c . )"

  if [ "$count" -eq 1 ]; then
    target="$(printf '%s\n' "$hits" | head -n1)"
    log "exec $target/sandbox/claude-web/setup.sh"
    # The PAT is exported ONLY onto this one verified command. It is never a
    # global export, so no other process in this stage inherits it.
    GH_AI_TOOLS_PAT="$PAT" exec bash "$target/sandbox/claude-web/setup.sh"
  fi

  if [ "$count" -eq 0 ]; then
    log "no tds-utils checkout found -- nothing to do here; the SessionStart hook provisions in-session."
  else
    log "REFUSING to guess among multiple checkouts (the PAT would go to whichever we picked):"
    printf '%s\n' "$hits" | while IFS= read -r c; do
      [ -n "$c" ] && log "  candidate: $c"
    done
  fi
}

# --- Main ---

main() {
  run_shim
  # The setup stage must never fail the environment build.
  exit 0
}

main "$@"
