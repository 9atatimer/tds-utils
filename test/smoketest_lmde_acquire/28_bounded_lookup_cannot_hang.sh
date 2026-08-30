#!/usr/bin/env bash
# Given no `timeout` binary (stock macOS) and a child that IGNORES SIGTERM and
# has spawned its own grandchild, When acquire_bounded runs it, Then the call
# returns near the bound rather than the child's full lifetime.
#
# This bound has been wrong twice, in two different ways, which is why it is
# tested directly rather than only through `lmde acquire`:
#
#   1. The `command -v timeout` guard fell through to running the command
#      UNBOUNDED when no timeout binary existed -- on the one platform the
#      fallback exists for (stock macOS ships neither timeout nor gtimeout).
#   2. The replacement sent SIGTERM and then waited. A child that ignores
#      SIGTERM -- a credential helper stuck on a locked keychain, the exact
#      case this guards -- left `wait` blocked forever. And because the child
#      was in the caller's process group, an orphaned grandchild kept the
#      command-substitution pipe open regardless: measured 30s against a 2s
#      bound even after the child itself was killed.
#
# So the assertion is wall-clock, against a deliberately hostile child.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir elapsed rc out
    dir="$(scenario_dir bounded_lookup)"

    # PATH without any timeout binary forces the fallback branch. Sourcing the
    # library directly is the point: this is the mechanism, not the verb.
    out="$(env -i HOME="${dir}/home" PATH=/usr/bin:/bin bash -c '
        source "'"${REPO_DIR}"'/lmde/lib/acquire.sh"
        start=$(date +%s)
        captured="$(acquire_bounded 2 bash -c "trap \"\" TERM; sleep 30 & sleep 30")"
        rc=$?
        end=$(date +%s)
        echo "$((end - start)) ${rc}"
    ')" || {
        echo "FAIL: bounded lookup aborted"
        return 1
    }
    elapsed="${out%% *}"
    rc="${out##* }"

    # Bound is 2s plus a 2s TERM->KILL grace; anything under 10 proves it did
    # not run the child's 30s lifetime. Deliberately loose: this asserts "a
    # bound exists", not a precise duration, so it stays stable on slow CI.
    if [ "${elapsed}" -ge 10 ]; then
        echo "FAIL: acquire_bounded did not bound a hostile child (elapsed ${elapsed}s, expected < 10s)"
        return 1
    fi
    assert_eq "${rc}" "124" "expiry reports 124, matching the timeout(1) branch" || return 1
}
main "$@"
