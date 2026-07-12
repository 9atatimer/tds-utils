#!/usr/bin/env bash
# run-probes.sh -- run both probes inside the current target and report.
#
# This is what actually executes *inside* the target session -- a laptop
# `clai claude` process (launched by run-laptop.sh) or a cloud Claude Code
# session. It prints every probe's PASS/FAIL/SKIP lines verbatim, then one
# machine-readable OVERALL line the driver greps for. Exit status is the
# total failure count (0 == green).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "${HERE}/lib.sh"

printf '=== LMDE/CLAI smoketest (env=%s, home=%s) ===\n' "$(env_label)" "${HOME}"

fails=0
for probe in probe-lmde.sh probe-clai.sh; do
  bash "${HERE}/${probe}"
  fails=$((fails + $?))
done

printf 'OVERALL env=%s failed=%d\n' "$(env_label)" "${fails}"
exit "${fails}"
