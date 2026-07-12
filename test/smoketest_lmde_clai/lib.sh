#!/usr/bin/env bash
# lib.sh -- shared helpers for the LMDE/CLAI behavioral smoketest.
#
# These are BLACK-BOX behavioral probes: they stand inside a real target
# (a laptop `clai claude` session, or a cloud Claude Code session) and
# interrogate the OBSERVABLE end-state a user/agent would see. They do NOT
# stub anything and they do NOT care which tool placed a given artifact
# (`lmde acquire` on a laptop, `@nine-at-a-time-media/sandbox` in the cloud).
# They assert only that the world looks the way the LMDE/CLAI design promises.
#
# Each check emits exactly one machine-readable line:
#   PASS <id> <desc>
#   FAIL <id> <desc> -- <detail>
#   SKIP <id> <desc> -- <reason>
# A probe ends with one summary line:
#   SMOKE-RESULT <probe> passed=<n> failed=<n> skipped=<n>
# and exits with its failure count (0 == green).

# --- counters (per sourcing process) ---------------------------------------
SMOKE_PASS=0
SMOKE_FAIL=0
SMOKE_SKIP=0

pass() { SMOKE_PASS=$((SMOKE_PASS + 1)); printf 'PASS %s %s\n' "$1" "$2"; }
fail() {
  SMOKE_FAIL=$((SMOKE_FAIL + 1))
  printf 'FAIL %s %s -- %s\n' "$1" "$2" "${3:-no detail}"
}
skip() {
  SMOKE_SKIP=$((SMOKE_SKIP + 1))
  printf 'SKIP %s %s -- %s\n' "$1" "$2" "${3:-n/a}"
}

# summarize <probe-name> ; returns failure count as exit status
summarize() {
  printf 'SMOKE-RESULT %s passed=%d failed=%d skipped=%d\n' \
    "$1" "$SMOKE_PASS" "$SMOKE_FAIL" "$SMOKE_SKIP"
  return "$SMOKE_FAIL"
}

# --- environment detection --------------------------------------------------
# is_cloud -- true only inside a Claude Code cloud sandbox. This is the same
# marker the real session-start hooks and shells gate on.
is_cloud() { [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; }

env_label() { if is_cloud; then printf 'cloud'; else printf 'laptop'; fi; }

# repo_root -- the project the agent has open. Prefer the session-provided
# CLAUDE_PROJECT_DIR, fall back to git, then to cwd. clai's project-scoped
# outputs (.mcp.json, .claude/skills) and per-project ~/.claude.json entries
# are all keyed off this path.
repo_root() {
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "${CLAUDE_PROJECT_DIR}" ]; then
    printf '%s' "${CLAUDE_PROJECT_DIR}"
    return 0
  fi
  local top
  if top="$(git rev-parse --show-toplevel 2>/dev/null)" && [ -n "$top" ]; then
    printf '%s' "$top"
    return 0
  fi
  printf '%s' "$PWD"
}

# have_jq -- jq is used for JSON assertions; probes SKIP (not FAIL) without it.
have_jq() { command -v jq >/dev/null 2>&1; }
