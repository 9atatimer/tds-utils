#!/usr/bin/env bash
# probe-chores.sh -- "does the herd actually run?"
#
# Kicks the tires of the chores herd (CHORES-ONE-TIME.DESIGN.md): the
# scheduler is installed and ticking, every smoketest one-time chore runs now
# and succeeds, and an armed run is started by the scheduler on time.
#
# Unlike the other probes this one ACTS: it runs the operator's `smoketest-*`
# chores (`schedule: manual`) from $CHORES_HOME and arms one. What they do and
# spend is the operator's definition, under its own budget and ceilings; this
# probe never chooses or writes one.
#
# Laptop only: the cloud has no herd, so every check SKIPs there.
# K3 waits at most two tick intervals for the scheduler -- the suite's one
# bounded wait.
#
# Usage:  bash probe-chores.sh
set -uo pipefail

# --- shared libraries ---
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "${HERE}/lib.sh"

POLL_SEC=5

# --- helpers ---

# status_json -- `chores status --json`, or nothing when chores is absent.
status_json() { chores status --json 2>/dev/null; }

# smoketest_chores <status-json> -- names of manual chores called smoketest-*.
smoketest_chores() {
  printf '%s' "$1" | jq -r '.chores[]
    | select(.name | startswith("smoketest-"))
    | select(.schedule == "manual")
    | .name'
}

# record_field <run-id> <jq-expr> -- one field of a run record, or empty.
record_field() {
  chores show "$1" --json 2>/dev/null | jq -r ".[0] | $2 // empty" 2>/dev/null
}

# --- checks ---

# K1 -- the scheduler is installed and not stale.
check_scheduler() {
  local status="$1" installed stale
  installed="$(printf '%s' "${status}" | jq -r '.scheduler.installed')"
  stale="$(printf '%s' "${status}" | jq -r '.scheduler.stale')"
  if [ "${installed}" = "true" ] && [ "${stale}" = "false" ]; then
    pass K1 "chores-scheduler-ticking"
    return 0
  fi
  fail K1 "chores-scheduler-ticking" "installed=${installed} stale=${stale}"
  return 1
}

# K2 -- every smoketest-* manual chore runs now and succeeds.
check_run_now() {
  local names="$1" name out rc failed=0
  for name in ${names}; do
    out="$(chores run "${name}" 2>&1)"
    rc=$?
    if [ "${rc}" -ne 0 ]; then
      failed=$((failed + 1))
      fail K2 "chores-run-now ${name}" "exit ${rc}: $(printf '%s' "${out}" | tail -n 1)"
    fi
  done
  [ "${failed}" -eq 0 ] && pass K2 "chores-run-now ($(printf '%s' "${names}" | wc -w | tr -d ' ') chore(s))"
}

# K3 -- an armed run is started by the scheduler within two tick intervals.
check_armed() {
  local name="$1" interval="$2" out run_id deadline state started start_at
  out="$(chores run "${name}" --at now 2>&1)" || {
    fail K3 "chores-armed-run" "arming ${name} failed: ${out}"
    return 0
  }
  run_id="$(printf '%s' "${out}" | sed -n 's/.*armed as \([^ ]*\).*/\1/p')"
  if [ -z "${run_id}" ]; then
    fail K3 "chores-armed-run" "no run id in: ${out}"
    return 0
  fi
  deadline=$(( $(date +%s) + 2 * interval + POLL_SEC ))
  state=""
  while [ "$(date +%s)" -le "${deadline}" ]; do
    state="$(record_field "${run_id}" '.status')"
    case "${state}" in
      SUCCEEDED) break ;;
      ARMED|PENDING|RUNNING|"") sleep "${POLL_SEC}" ;;
      *) break ;;
    esac
  done
  if [ "${state}" != "SUCCEEDED" ]; then
    [ "${state}" = "ARMED" ] && chores cancel "${run_id}" >/dev/null 2>&1
    fail K3 "chores-armed-run ${name}" "${run_id} is ${state:-missing} after $((2 * interval))s"
    return 0
  fi
  started="$(record_field "${run_id}" '.started')"
  start_at="$(record_field "${run_id}" '.start_at')"
  if [[ "${started}" < "${start_at}" ]]; then
    fail K3 "chores-armed-run ${name}" "started ${started} before start_at ${start_at}"
    return 0
  fi
  pass K3 "chores-armed-run (${run_id})"
}

# --- main ---

main() {
  local status names interval
  if is_cloud; then
    skip K1 "chores-scheduler-ticking" "cloud: no herd"
    skip K2 "chores-run-now" "cloud: no herd"
    skip K3 "chores-armed-run" "cloud: no herd"
  elif ! have_jq; then
    skip K1 "chores-scheduler-ticking" "jq not installed"
    skip K2 "chores-run-now" "jq not installed"
    skip K3 "chores-armed-run" "jq not installed"
  else
    status="$(status_json)"
    if [ -z "${status}" ]; then
      fail K1 "chores-scheduler-ticking" "chores not on PATH or 'chores status --json' failed"
      skip K2 "chores-run-now" "K1: herd unavailable"
      skip K3 "chores-armed-run" "K1: herd unavailable"
    elif ! check_scheduler "${status}"; then
      skip K2 "chores-run-now" "K1: scheduler not ticking"
      skip K3 "chores-armed-run" "K1: scheduler not ticking"
    else
      names="$(smoketest_chores "${status}")"
      if [ -z "${names}" ]; then
        fail K2 "chores-run-now" "no smoketest-* chore with schedule: manual in \$CHORES_HOME"
        fail K3 "chores-armed-run" "no smoketest-* chore with schedule: manual in \$CHORES_HOME"
      else
        check_run_now "${names}"
        interval="$(printf '%s' "${status}" | jq -r '.scheduler.tick_interval_sec // 60')"
        check_armed "$(printf '%s\n' "${names}" | head -n 1)" "${interval}"
      fi
    fi
  fi
  summarize probe-chores
}

main "$@"
