#!/usr/bin/env bash
# Given no `timeout` binary, a child that DIES on SIGTERM, and a grandchild
# that IGNORES it while holding the inherited stdout, When acquire_bounded runs
# the child, Then the call returns near the bound rather than the grandchild's
# lifetime.
#
# This is the complement of scenario 28, and the distinction is the whole
# point. In 28 the LEADER ignores SIGTERM, so the grace loop's `kill -0 <pid>`
# probe stays true, the loop runs its course, and SIGKILL reaches the group.
# Here the leader dies from the TERM we sent. Probing only the leader ends the
# grace loop immediately, SIGKILL is never sent, and the surviving grandchild
# holds the caller's command-substitution pipe open for its full lifetime.
#
# Measured against the pre-fix code: 31s elapsed against a 2s bound -- while
# rc was still 124, so the status looked correct and only the wall clock
# disagreed. A bound that reports success without bounding anything is the
# failure this whole family of tests exists to catch.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir bindir child elapsed rc out
    dir="$(scenario_dir bounded_descendants)"
    bindir="$(no_timeout_path "${dir}")" || return 1
    child="$(hostile_child "${dir}")"

    # The leader takes SIGTERM at default disposition and dies; the grandchild
    # ignores it and keeps stdout. Only a group-wide SIGKILL ends this.
    out="$(env -i HOME="${dir}/home" PATH="${bindir}" bash -c '
        source "'"${REPO_DIR}"'/lmde/lib/acquire.sh"
        start=$(date +%s)
        captured="$(acquire_bounded 2 bash -c "'"${child}"' & sleep 30")"
        rc=$?
        end=$(date +%s)
        echo "$((end - start)) ${rc}"
    ')" || {
        echo "FAIL: bounded lookup aborted"
        return 1
    }
    elapsed="${out%% *}"
    rc="${out##* }"

    if [ "${elapsed}" -ge 10 ]; then
        echo "FAIL: acquire_bounded did not kill a surviving descendant (elapsed ${elapsed}s, expected < 10s)"
        return 1
    fi
    assert_eq "${rc}" "124" "expiry reports 124, matching the timeout(1) branch" || return 1
}
main "$@"
