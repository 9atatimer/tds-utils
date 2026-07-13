#!/usr/bin/env bash
# run-probes.sh -- run both probes inside the current target and report.
#
# This is what actually executes *inside* the target session -- a laptop
# `clai claude` process (launched by run-laptop.sh) or a cloud Claude Code
# session. It prints every probe's PASS/FAIL/SKIP lines verbatim, then one
# machine-readable OVERALL line the driver greps for. Exit status is the
# total failure count (0 == green).
#
# Prerequisites: run from inside the target session. No -e: a probe returning
# nonzero (its failure count) is data to accumulate, not a reason to abort.
#
# Usage:  bash run-probes.sh
set -uo pipefail

# --- shared libraries ---
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "${HERE}/lib.sh"

# --- helpers ---

# run_probe <probe-basename> -- execute one probe; its exit status is its
# failure count, which the caller accumulates.
run_probe() {
  bash "${HERE}/$1"
}

# --- main ---
main() {
  local fails=0 rc probe
  printf '=== LMDE/CLAI smoketest (env=%s, home=%s) ===\n' "$(env_label)" "${HOME}"
  for probe in probe-lmde.sh probe-clai.sh; do
    run_probe "${probe}"
    rc=$?
    fails=$((fails + rc))
  done
  printf 'OVERALL env=%s failed=%d\n' "$(env_label)" "${fails}"
  return "${fails}"
}

main "$@"
