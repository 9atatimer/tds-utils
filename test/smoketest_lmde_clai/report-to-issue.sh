#!/usr/bin/env bash
# report-to-issue.sh -- run the LMDE/CLAI smoketest and record the result on a
# single tracking GitHub issue, so the outcome is fetchable via `gh` from
# anywhere (no browser or console access needed).
#
# Behaviour:
#   - Runs run-probes.sh and reads the OVERALL line (env + failed count).
#   - Ensures a tracking issue exists (the most recent one labelled `smoketest`;
#     creates one if none exists -- assumes the label is not manually
#     duplicated), then appends a comment with the verdict, env, timestamp, and
#     full probe output. The issue state is only changed once that comment posts,
#     so a state change always has a corresponding recorded result.
#   - PASS (failed=0): close the issue and drop the fail label (closed = green).
#   - FAIL: reopen it and add the `smoketest-fail` label (open bug = broken).
#   - Prints a final `OVERALL ... verdict=... issue=#N` line.
#
# Fetch the latest result from a laptop with:
#   gh issue view <N> --repo 9atatimer/tds-utils --json state,labels,comments
#
# Prerequisites: gh authenticated with issues:write on the repo. No -e: gh
# hiccups are handled explicitly; the probe result is the point.
#
# Usage:  test/smoketest_lmde_clai/report-to-issue.sh [--dry-run]
set -uo pipefail

# --- config ---
REPO="9atatimer/tds-utils"
LABEL="smoketest"
FAIL_LABEL="smoketest-fail"
TITLE="LMDE/CLAI smoketest -- status"

# --- shared location ---
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- helpers ---

# run_probes -- execute the suite and echo its full stdout (PASS/FAIL/OVERALL).
run_probes() {
  bash "${HERE}/run-probes.sh" 2>&1
}

# parse_field <output> <sed-expr> -- pull one value from the OVERALL line.
parse_field() {
  printf '%s\n' "$1" | sed -n "$2" | tail -n 1
}

# ensure_labels -- create the tracking labels if absent (idempotent, best-effort).
ensure_labels() {
  gh label create "${LABEL}" --repo "${REPO}" --color 0e8a16 \
    --description "LMDE/CLAI smoketest status" >/dev/null 2>&1 || true
  gh label create "${FAIL_LABEL}" --repo "${REPO}" --color b60205 \
    --description "LMDE/CLAI smoketest is failing" >/dev/null 2>&1 || true
}

# find_issue -- number of the existing tracking issue (open or closed), or empty.
find_issue() {
  gh issue list --repo "${REPO}" --label "${LABEL}" --state all --limit 1 \
    --json number --jq '.[0].number // empty' 2>/dev/null
}

# issue_description <issue-number> -- the static body for the tracking issue,
# with the real issue number baked into the fetch command (no placeholder).
issue_description() {
  printf 'Tracking issue for the LMDE/CLAI behavioural smoketest (`%s`).\n\nEach run appends a comment with the full probe output. The issue is CLOSED when the latest run passes and OPEN (label `%s`) when it fails. Fetch the latest result from the most recent comment:\n\n    gh issue view %s --repo %s --json state,comments\n' \
    "test/smoketest_lmde_clai" "${FAIL_LABEL}" "$1" "${REPO}"
}

# --- main ---
main() {
  local dry="${1:-}" output failed env verdict ts body num

  output="$(run_probes)"
  failed="$(parse_field "${output}" 's/^OVERALL .*failed=\([0-9][0-9]*\).*/\1/p')"
  env="$(parse_field "${output}" 's/^OVERALL env=\([a-z][a-z]*\) .*/\1/p')"
  [ -n "${failed}" ] || failed=99          # no OVERALL line -> treat as failure
  [ -n "${env}" ] || env="unknown"
  if [ "${failed}" -eq 0 ]; then verdict="PASS"; else verdict="FAIL"; fi
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  body="$(printf '### %s -- env=%s -- %s\n\n```\n%s\n```\n' \
    "${verdict}" "${env}" "${ts}" "${output}")"

  if [ "${dry}" = "--dry-run" ]; then
    printf 'DRY-RUN (no GitHub writes)\n%s\n---\nwould: %s tracking issue\n' \
      "${body}" "$([ "${verdict}" = PASS ] && echo 'comment + close' || echo 'comment + reopen + fail-label')"
    printf 'OVERALL env=%s failed=%s verdict=%s\n' "${env}" "${failed}" "${verdict}"
    return 0
  fi

  ensure_labels
  num="$(find_issue)"
  if [ -z "${num}" ]; then
    # First run: create with a placeholder body, then rewrite it with the real
    # issue number baked in (the number isn't known until after creation). Each
    # run's result is a comment, so "latest result = most recent comment".
    num="$(gh issue create --repo "${REPO}" --title "${TITLE}" --label "${LABEL}" \
      --body "Bootstrapping LMDE/CLAI smoketest tracking issue..." 2>/dev/null \
      | sed -n 's#.*/issues/\([0-9][0-9]*\).*#\1#p')"
    if [ -n "${num}" ]; then
      echo "created tracking issue #${num}"
      gh issue edit "${num}" --repo "${REPO}" --body "$(issue_description "${num}")" >/dev/null 2>&1 || true
    fi
  fi
  if [ -z "${num}" ]; then
    echo "ERROR: could not create or find the tracking issue"
    printf 'OVERALL env=%s failed=%s verdict=%s issue=none\n' "${env}" "${failed}" "${verdict}"
    return 1
  fi

  # Record the result BEFORE touching issue state, and only change state if the
  # comment posts -- so a state change always has a corresponding recorded run.
  if gh issue comment "${num}" --repo "${REPO}" --body "${body}" >/dev/null 2>&1; then
    echo "commented result on issue #${num}"
  else
    echo "WARNING: could not post result comment on #${num}; leaving issue state unchanged"
    printf 'OVERALL env=%s failed=%s verdict=%s issue=#%s comment=failed\n' \
      "${env}" "${failed}" "${verdict}" "${num}"
    return 1
  fi

  if [ "${verdict}" = "PASS" ]; then
    gh issue edit "${num}" --repo "${REPO}" --remove-label "${FAIL_LABEL}" >/dev/null 2>&1 || true
    gh issue close "${num}" --repo "${REPO}" --reason completed >/dev/null 2>&1 \
      && echo "closed #${num} (PASS)"
  else
    gh issue edit "${num}" --repo "${REPO}" --add-label "${FAIL_LABEL}" >/dev/null 2>&1 || true
    gh issue reopen "${num}" --repo "${REPO}" >/dev/null 2>&1 || true
    echo "left #${num} OPEN (FAIL)"
  fi

  printf 'OVERALL env=%s failed=%s verdict=%s issue=#%s\n' "${env}" "${failed}" "${verdict}" "${num}"
}

main "$@"
