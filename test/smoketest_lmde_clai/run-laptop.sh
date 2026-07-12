#!/usr/bin/env bash
# run-laptop.sh -- laptop driver for the LMDE/CLAI behavioral smoketest.
#
# Spins up a REAL headless claude session through clai (so clai's launch hooks
# fire and its injected env is live in the process the probes observe), asks it
# to run the probes, and grades the result. This is the "spin up a claude
# session and ask it what it sees" check, on the laptop.
#
# The session runs with cwd == the tds-utils checkout so the repo-scoped clai.d
# hooks, .mcp.json, and .claude/skills all apply. CLAUDE_CODE_REMOTE is stripped
# from the launched env so a stray value in the caller's shell cannot make the
# probes false-detect cloud.
#
# Prerequisites: clai + claude on PATH; costs a little quota (~30-60s).
#
# Usage:  test/smoketest_lmde_clai/run-laptop.sh
set -euo pipefail

# --- module state ---
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- helpers ---

# require_clai -- fail fast with an actionable message if clai is absent.
require_clai() {
  command -v clai >/dev/null 2>&1 || { echo "FAIL: clai not on PATH"; exit 2; }
}

# launch_session <repo-root> <probe-path> -- run the probe inside a real
# headless `clai claude` session and echo its combined output. Unsetting
# CLAUDE_CODE_REMOTE forces the laptop column regardless of the caller's shell.
launch_session() {
  local root="$1" probe="$2" qprobe prompt
  # shell-escape the path so a checkout dir with spaces still runs cleanly
  printf -v qprobe '%q' "${probe}"
  prompt="Run exactly this command with the Bash tool and print its stdout verbatim, with no commentary before or after: bash ${qprobe}"
  echo "== launching: clai claude -p (cwd=${root}) ==" >&2
  # --dangerously-skip-permissions alone bypasses all prompts (matches the repo's
  # documented usage in macos/dot.alias); no separate --permission-mode needed.
  ( cd "${root}" && env -u CLAUDE_CODE_REMOTE clai claude -p "${prompt}" \
      --output-format text \
      --dangerously-skip-permissions 2>&1 ) || true
}

# grade <session-output> -- turn the session's OVERALL line into a verdict and
# exit status (0 green, 1 failing checks, 3 no result).
grade() {
  local out="$1" failed
  if ! printf '%s\n' "${out}" | grep -q '^OVERALL '; then
    echo "SMOKE: no OVERALL line -- the session did not run the probes"
    return 3
  fi
  failed="$(printf '%s\n' "${out}" | sed -n 's/^OVERALL .*failed=\([0-9][0-9]*\).*/\1/p' | tail -1)"
  if [ "${failed:-1}" -eq 0 ]; then
    echo "SMOKE: PASS (laptop)"
    return 0
  fi
  echo "SMOKE: FAIL (laptop) -- ${failed} failing check(s):"
  printf '%s\n' "${out}" | grep '^FAIL ' || true
  return 1
}

# --- main ---
main() {
  local root out
  require_clai
  root="$(git -C "${HERE}" rev-parse --show-toplevel)"
  out="$(launch_session "${root}" "${HERE}/run-probes.sh")"
  printf '%s\n' "${out}"
  echo "== grading =="
  grade "${out}"
}

main "$@"
