#!/usr/bin/env bash
# Given a `timeout` binary IS present and a child that ignores SIGTERM, When
# acquire_bounded runs it, Then the call returns near the bound.
#
# Scenarios 28 and 29 both force the no-timeout FALLBACK, because that is the
# branch stock macOS takes. Every Linux machine takes the other one -- and it
# had never been tested. It was not bounded: `timeout <secs> <cmd>` sends only
# SIGTERM and then waits, so a child that ignores SIGTERM is waited on for its
# full lifetime. Measured on GNU coreutils 9.11: 31s against a 2s bound, exit
# 124, i.e. reporting the bound as honored.
#
# That is issue #256, and it mattered more than the fallback bugs did: the
# credential helper stuck on a locked keychain -- the case acquire_bounded was
# written for -- is exactly a child that does not service SIGTERM, and
# `lmde acquire --check` runs from git-hooks/pre-push, so the symptom is a push
# that hangs.
#
# Skips loudly rather than failing where no timeout binary exists (stock macOS),
# since there the branch under test is unreachable by construction.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir bindir child elapsed rc out
    dir="$(scenario_dir bounded_timeout_branch)"

    if ! bindir="$(timeout_path "${dir}")"; then
        echo "SKIP: no timeout/gtimeout on host PATH; primary branch unreachable"
        return 0
    fi
    child="$(hostile_child "${dir}")"

    out="$(env -i HOME="${dir}/home" PATH="${bindir}" bash -c '
        source "'"${REPO_DIR}"'/lmde/lib/acquire.sh"
        start=$(date +%s)
        captured="$(acquire_bounded 2 "'"${child}"'")"
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
        echo "FAIL: timeout branch did not bound a SIGTERM-ignoring child (elapsed ${elapsed}s, expected < 10s)"
        return 1
    fi
    assert_eq "${rc}" "124" "expiry reports 124 on the timeout branch" || return 1
}
main "$@"
