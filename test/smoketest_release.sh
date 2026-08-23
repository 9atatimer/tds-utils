#!/usr/bin/env bash
# smoketest_release.sh -- behavioral smoke test for bin/tds-release.
#
# Hermetic: no network, no sleeps, no real remote. Each case builds a throwaway
# git repo with a `master` branch, a `release` branch, and a `release` worktree, then
# drives the releaser at it via TDS_RELEASE_REPO with fetch and push disabled
# (TDS_RELEASE_FETCH=0 / TDS_RELEASE_PUSH=0).
#
# Usage: ./test/smoketest_release.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
RELEASER="${REPO_DIR}/bin/tds-release"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1" condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

cleanup() { [ -n "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixture ---------------------------------------------------------------

# make_repo <name> -- a repo on master with a `release` branch and release worktree.
# Echoes the repo root. `release` starts one commit behind master's tip.
make_repo() {
    local name="$1"
    local root="${WORKROOT}/${name}"
    local wt="${WORKROOT}/${name}-release"
    mkdir -p "${root}"
    git -C "${root}" init -q -b master
    git -C "${root}" config user.email t@example.com
    git -C "${root}" config user.name  Test
    echo one > "${root}/f"
    git -C "${root}" add f
    git -C "${root}" commit -qm one
    git -C "${root}" branch release
    echo two > "${root}/f"
    git -C "${root}" commit -qam two
    git -C "${root}" worktree add -q "${wt}" release
    printf '%s\n' "${root}"
}

release_wt()  { printf '%s\n' "${WORKROOT}/$1-release"; }
head_of()  { git -C "$1" rev-parse HEAD; }
branch_of(){ git -C "$1" rev-parse --abbrev-ref HEAD; }

# run_release <repo> [args...] -- returns the releaser's exit status
run_release() {
    local root="$1"; shift
    TDS_RELEASE_REPO="${root}" TDS_RELEASE_FETCH=0 TDS_RELEASE_PUSH=0 \
        "${RELEASER}" "$@" >"${WORKROOT}/out" 2>&1
}

# --- Cases -----------------------------------------------------------------

case_fast_forward() {
    bold "case: fast-forward release"; echo
    local root wt before
    root="$(make_repo ff)"; wt="$(release_wt ff)"
    before="$(head_of "${wt}")"
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits 0"                     "[ ${rc} -eq 0 ]"
    assert "release advanced to master"     "[ \"$(head_of "${wt}")\" = \"$(git -C "${root}" rev-parse master)\" ]"
    assert "release moved off old commit"   "[ \"$(head_of "${wt}")\" != \"${before}\" ]"
    assert "worktree still on release"      "[ \"$(branch_of "${wt}")\" = release ]"
}

case_already_current() {
    bold "case: already up to date"; echo
    local root wt
    root="$(make_repo cur)"; wt="$(release_wt cur)"
    run_release "${root}" master
    local at
    at="$(head_of "${wt}")"
    run_release "${root}" master && rc=0 || rc=$?
    assert "second run exits 0"          "[ ${rc} -eq 0 ]"
    assert "release unchanged"              "[ \"$(head_of "${wt}")\" = \"${at}\" ]"
    assert "says up to date"             "grep -qi 'up to date' '${WORKROOT}/out'"
}

case_non_ff_refused() {
    bold "case: non-fast-forward refused"; echo
    local root wt before
    root="$(make_repo nff)"; wt="$(release_wt nff)"
    echo divergent > "${wt}/f"
    git -C "${wt}" commit -qam divergent
    before="$(head_of "${wt}")"
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "release unchanged"              "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
    assert "explains fast-forward"       "grep -qi 'fast-forward' '${WORKROOT}/out'"
}

case_dirty_refused() {
    bold "case: dirty release worktree refused"; echo
    local root wt before
    root="$(make_repo dirty)"; wt="$(release_wt dirty)"
    before="$(head_of "${wt}")"
    echo scribble >> "${wt}/f"
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "release unchanged"              "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
    assert "explains dirty tree"         "grep -qiE 'dirty|uncommitted' '${WORKROOT}/out'"
}

case_dry_run() {
    bold "case: dry run does not move release"; echo
    local root wt before
    root="$(make_repo dry)"; wt="$(release_wt dry)"
    before="$(head_of "${wt}")"
    run_release "${root}" -n master && rc=0 || rc=$?
    assert "exits 0"                     "[ ${rc} -eq 0 ]"
    assert "release unchanged"              "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
    assert "reports the pending commit"  "grep -q 'two' '${WORKROOT}/out'"
}

case_no_release_worktree() {
    bold "case: missing release worktree refused"; echo
    local root="${WORKROOT}/bare"
    mkdir -p "${root}"
    git -C "${root}" init -q -b master
    git -C "${root}" config user.email t@example.com
    git -C "${root}" config user.name  Test
    echo one > "${root}/f"; git -C "${root}" add f; git -C "${root}" commit -qm one
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "names the release worktree"     "grep -qi 'release' '${WORKROOT}/out'"
}

case_unreviewed_target_refused() {
    bold "case: a commit outside master history is refused"; echo
    local root wt before topic
    root="$(make_repo unrev)"; wt="$(release_wt unrev)"
    before="$(head_of "${wt}")"
    # A topic commit that descends from release but was never merged to master:
    # fast-forwardable, and exactly the thing that must not go live.
    git -C "${root}" checkout -q -b topic release
    echo unreviewed > "${root}/f"
    git -C "${root}" commit -qam unreviewed
    topic="$(git -C "${root}" rev-parse topic)"
    git -C "${root}" checkout -q master
    run_release "${root}" "${topic}" && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "release unchanged"           "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
    assert "explains reviewed history"   "grep -qiE 'master|reviewed' '${WORKROOT}/out'"
}

case_unreviewed_target_refused_under_force() {
    bold "case: -f does not bypass the reviewed-history guard"; echo
    local root wt before topic
    root="$(make_repo unrevf)"; wt="$(release_wt unrevf)"
    before="$(head_of "${wt}")"
    git -C "${root}" checkout -q -b topic release
    echo unreviewed > "${root}/f"
    git -C "${root}" commit -qam unreviewed
    topic="$(git -C "${root}" rev-parse topic)"
    git -C "${root}" checkout -q master
    run_release "${root}" -f "${topic}" && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "release unchanged"           "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
}

case_dirty_beats_up_to_date() {
    bold "case: a dirty release tree is reported even when already current"; echo
    local root wt
    root="$(make_repo dirtycur)"; wt="$(release_wt dirtycur)"
    run_release "${root}" master
    # HEAD now equals the target; the tree is what is wrong.
    echo scribble >> "${wt}/f"
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "explains dirty tree"         "grep -qiE 'dirty|uncommitted' '${WORKROOT}/out'"
    assert "does not claim up to date"   "! grep -qi 'up to date' '${WORKROOT}/out'"
}

main() {
    [ -x "${RELEASER}" ] || { red "FAIL"; printf ' missing or non-executable: %s\n' "${RELEASER}"; exit 1; }
    WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/release-test.XXXXXX")"
    case_fast_forward
    case_already_current
    case_non_ff_refused
    case_dirty_refused
    case_dry_run
    case_no_release_worktree
    case_unreviewed_target_refused
    case_unreviewed_target_refused_under_force
    case_dirty_beats_up_to_date
    echo
    printf 'ran %d, passed %d, failed %d\n' "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
