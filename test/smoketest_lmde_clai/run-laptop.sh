#!/usr/bin/env bash
# run-laptop.sh -- laptop driver for the LMDE/CLAI behavioral smoketest.
#
# Spins up a REAL headless claude session through clai (so clai's launch hooks
# fire and its injected env is live in the process the probes observe), asks it
# to run the probes, and grades the result. This is the "spin up a claude
# session and ask it what it sees" check, on the laptop.
#
# The session must run with cwd == the tds-utils checkout so the repo-scoped
# clai.d hooks, .mcp.json, and .claude/skills all apply.
#
# Usage:  test/smoketest_lmde_clai/run-laptop.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "${HERE}" rev-parse --show-toplevel)"

command -v clai >/dev/null 2>&1 || { echo "FAIL: clai not on PATH"; exit 2; }

PROBE="${HERE}/run-probes.sh"
PROMPT="Run exactly this command with the Bash tool and print its stdout verbatim, with no commentary before or after: bash ${PROBE}"

echo "== launching: clai claude -p (cwd=${ROOT}) =="
# clai forwards everything after the agent name to claude verbatim.
out="$(cd "${ROOT}" && clai claude -p "${PROMPT}" \
  --output-format text \
  --permission-mode bypassPermissions \
  --dangerously-skip-permissions 2>&1)" || true

printf '%s\n' "${out}"
echo "== grading =="

if ! printf '%s\n' "${out}" | grep -q '^OVERALL '; then
  echo "SMOKE: no OVERALL line -- the session did not run the probes"
  exit 3
fi

failed="$(printf '%s\n' "${out}" | sed -n 's/^OVERALL .*failed=\([0-9][0-9]*\).*/\1/p' | tail -1)"
if [ "${failed:-1}" -eq 0 ]; then
  echo "SMOKE: PASS (laptop)"
  exit 0
fi
echo "SMOKE: FAIL (laptop) -- ${failed} failing check(s):"
printf '%s\n' "${out}" | grep '^FAIL ' || true
exit 1
