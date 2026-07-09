PAT='PASTE-CLASSIC-read:packages-PAT-HERE'
# Paste into the Claude web Environment "Setup script". PAT stays on line 1.
# All logic lives in the repo's setup.sh, which this execs -- never re-paste.
# No shebang (the PAT owns line 1), so lint with: shellcheck -s bash

set -uo pipefail

log() { printf '[tds shim] %s\n' "$*" >&2; }

# Three markers: an unrelated repo cloned alongside must never match.
is_checkout() {
  [ -n "${1:-}" ] \
    && [ -f "$1/sandbox/claude-web/setup.sh" ] \
    && [ -f "$1/sandbox/provision.sh" ] \
    && [ -f "$1/.mcp.json" ]
}

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

exec_setup() {
  local target="$1"
  log "exec $target/sandbox/claude-web/setup.sh"
  # execfail: without it a failed exec exits 127, and this stage must exit 0.
  shopt -s execfail
  # PAT is exported onto this one verified command, never globally.
  GH_AI_TOOLS_PAT="$PAT" exec bash "$target/sandbox/claude-web/setup.sh"
  log "exec failed -- setup.sh did not run; the SessionStart hook provisions in-session."
}

run_shim() {
  local hits count
  hits="$(find_checkouts)"
  count="$(printf '%s\n' "$hits" | grep -c . )"

  case "$count" in
    1) exec_setup "$(printf '%s\n' "$hits" | head -n1)" ;;
    0) log "no tds-utils checkout found -- the SessionStart hook provisions in-session." ;;
    *) log "REFUSING to guess among multiple checkouts:"
       printf '%s\n' "$hits" | while IFS= read -r c; do
         [ -n "$c" ] && log "  candidate: $c"
       done ;;
  esac
}

main() {
  run_shim
  exit 0   # never fail the environment build
}

main "$@"
