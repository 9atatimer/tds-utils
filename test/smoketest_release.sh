#!/usr/bin/env bash
# smoketest_release.sh -- behavioral smoke test for bin/tds-release.
#
# Hermetic: no network, no sleeps, no real remote. Each case builds a throwaway
# git repo with a `master` branch, a `release` branch, and a `release` worktree, then
# drives the releaser at it via TDS_RELEASE_REPO with fetch and push disabled
# (TDS_RELEASE_FETCH=0 / TDS_RELEASE_PUSH=0).
#
# The releaser handles more than one release unit -- the public repo it ships
# in, and the private repo (tds-internal) when the machine has one. The second
# unit is shimmed with TDS_RELEASE_PRIVATE_REPO, which every case below
# defaults to a path that cannot exist, so a case that does not opt in can
# never reach this machine's real private checkout.
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
    TDS_RELEASE_PRIVATE_REPO="${TDS_RELEASE_PRIVATE_REPO:-${WORKROOT}/no-such-private-repo}" \
        "${RELEASER}" "$@" >"${WORKROOT}/out" 2>&1
}

# run_release_units <public-repo> <private-repo> [args...] -- both units armed
run_release_units() {
    local pub="$1" priv="$2"; shift 2
    TDS_RELEASE_PRIVATE_REPO="${priv}" run_release "${pub}" "$@"
}

# make_repo_on <name> <default-branch> -- make_repo, but for a repo whose
# reviewed line is not `master`. The private repo's is `main`, and the releaser
# must not have that branch name baked into it.
make_repo_on() {
    local name="$1" line="$2"
    local root="${WORKROOT}/${name}"
    local wt="${WORKROOT}/${name}-release"
    mkdir -p "${root}"
    git -C "${root}" init -q -b "${line}"
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

# add_sentry <repo> <reason> -- commit a NO.RELEASE onto master.
add_sentry() {
    local root="$1" reason="$2"
    printf '%s\n' "${reason}" > "${root}/NO.RELEASE"
    git -C "${root}" add NO.RELEASE
    git -C "${root}" commit -qm "add NO.RELEASE"
}

case_sentry_blocks_release() {
    bold "case: NO.RELEASE on the target refuses the release"; echo
    local root wt before
    root="$(make_repo sentry)"; wt="$(release_wt sentry)"
    add_sentry "${root}" "migration must run by hand first"
    before="$(head_of "${wt}")"
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "release unchanged"           "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
    assert "names the sentry"            "grep -q 'NO.RELEASE' '${WORKROOT}/out'"
    assert "prints the recorded reason"  "grep -q 'migration must run by hand first' '${WORKROOT}/out'"
}

case_sentry_blocks_dry_run() {
    bold "case: NO.RELEASE refuses the dry run too"; echo
    local root
    root="$(make_repo sentrydry)"
    add_sentry "${root}" "held: pending manual step"
    run_release "${root}" -n master && rc=0 || rc=$?
    assert "dry run exits non-zero"      "[ ${rc} -ne 0 ]"
    assert "does not say would release"  "! grep -qi 'would release' '${WORKROOT}/out'"
}

case_sentry_removed_releases() {
    bold "case: removing NO.RELEASE unblocks the next commit"; echo
    local root wt
    root="$(make_repo sentrygone)"; wt="$(release_wt sentrygone)"
    add_sentry "${root}" "hold"
    git -C "${root}" rm -q NO.RELEASE
    git -C "${root}" commit -qm "release again"
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits 0"                     "[ ${rc} -eq 0 ]"
    assert "release advanced"            "[ \"$(head_of "${wt}")\" = \"$(git -C "${root}" rev-parse master)\" ]"
}

case_sentry_checked_on_target_not_current() {
    bold "case: the sentry is read from the target, not the live release"; echo
    local root wt held
    root="$(make_repo sentrylive)"; wt="$(release_wt sentrylive)"
    add_sentry "${root}" "hold"
    held="$(git -C "${root}" rev-parse master)"
    git -C "${root}" rm -q NO.RELEASE
    git -C "${root}" commit -qm "clear the hold"
    # Release the clean tip, then confirm the held commit is still refused --
    # the check must read the commit being released, not the working tree and
    # not whatever release currently points at.
    run_release "${root}" master
    assert "clean tip released"          "[ \"$(head_of "${wt}")\" = \"$(git -C "${root}" rev-parse master)\" ]"
    run_release "${root}" -f "${held}" && rc=0 || rc=$?
    assert "held commit still refused"   "[ ${rc} -ne 0 ]"
    assert "-f does not bypass it"       "grep -q 'NO.RELEASE' '${WORKROOT}/out'"
}

case_empty_sentry_blocks_release() {
    bold "case: an EMPTY NO.RELEASE still refuses"; echo
    local root wt before
    root="$(make_repo emptysentry)"; wt="$(release_wt emptysentry)"
    # `touch NO.RELEASE` is the obvious way to hold a release. Keying the gate
    # off the file's CONTENT rather than its presence would fail open here --
    # the one direction a safety gate must never fail.
    : > "${root}/NO.RELEASE"
    git -C "${root}" add NO.RELEASE
    git -C "${root}" commit -qm "hold, no reason given"
    before="$(head_of "${wt}")"
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "release unchanged"           "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
    assert "names the sentry"            "grep -q 'NO.RELEASE' '${WORKROOT}/out'"
    assert "says no reason recorded"     "grep -qi 'no reason recorded' '${WORKROOT}/out'"
}

case_whitespace_sentry_blocks_release() {
    bold "case: a whitespace-only NO.RELEASE still refuses"; echo
    local root wt before
    root="$(make_repo wssentry)"; wt="$(release_wt wssentry)"
    printf '\n  \n\t\n' > "${root}/NO.RELEASE"
    git -C "${root}" add NO.RELEASE
    git -C "${root}" commit -qm "hold, blank reason"
    before="$(head_of "${wt}")"
    run_release "${root}" master && rc=0 || rc=$?
    assert "exits non-zero"              "[ ${rc} -ne 0 ]"
    assert "release unchanged"           "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
}


# --- The private release unit ----------------------------------------------

case_private_unit_advances() {
    bold "case: the private unit is released alongside the public one"; echo
    local pub priv rc
    pub="$(make_repo pubA)"; priv="$(make_repo_on privA main)"
    run_release_units "${pub}" "${priv}" && rc=0 || rc=$?
    assert "exits 0" "[ ${rc} -eq 0 ]"
    assert "public release advanced" \
        "[ \"$(head_of "$(release_wt pubA)")\" = \"$(git -C "${pub}" rev-parse master)\" ]"
    assert "private release advanced to its own line (main)" \
        "[ \"$(head_of "$(release_wt privA)")\" = \"$(git -C "${priv}" rev-parse main)\" ]"
    assert "private worktree still on release" \
        "[ \"$(branch_of "$(release_wt privA)")\" = release ]"
}

case_absent_private_unit_is_a_skip() {
    bold "case: no private checkout is a skip, not a failure"; echo
    local pub rc
    pub="$(make_repo pubB)"
    run_release_units "${pub}" "${WORKROOT}/definitely-not-here" && rc=0 || rc=$?
    assert "exits 0"                  "[ ${rc} -eq 0 ]"
    assert "public release happened"  \
        "[ \"$(head_of "$(release_wt pubB)")\" = \"$(git -C "${pub}" rev-parse master)\" ]"
    assert "says the unit was skipped" "grep -qi 'skip' '${WORKROOT}/out'"
}

case_private_unit_without_a_release_worktree_is_a_skip() {
    bold "case: a private checkout with no release worktree is a skip"; echo
    local pub priv rc
    pub="$(make_repo pubC)"
    priv="${WORKROOT}/privC"
    mkdir -p "${priv}"
    git -C "${priv}" init -q -b main
    git -C "${priv}" config user.email t@example.com
    git -C "${priv}" config user.name Test
    echo x > "${priv}/f"; git -C "${priv}" add f; git -C "${priv}" commit -qm one
    run_release_units "${pub}" "${priv}" && rc=0 || rc=$?
    assert "exits 0"                   "[ ${rc} -eq 0 ]"
    assert "says the unit was skipped" "grep -qi 'skip' '${WORKROOT}/out'"
}

case_dirty_private_unit_refused() {
    bold "case: a dirty private release worktree refuses"; echo
    local pub priv wt rc before
    pub="$(make_repo pubD)"; priv="$(make_repo_on privD main)"; wt="$(release_wt privD)"
    before="$(head_of "${wt}")"
    echo scribble >> "${wt}/f"
    run_release_units "${pub}" "${priv}" && rc=0 || rc=$?
    assert "exits nonzero"            "[ ${rc} -ne 0 ]"
    assert "private did not move"     "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
    assert "reports uncommitted work" "grep -q 'uncommitted changes' '${WORKROOT}/out'"
}

case_private_sentry_blocks_its_own_unit() {
    bold "case: NO.RELEASE on the private unit holds that unit"; echo
    local pub priv wt rc before
    pub="$(make_repo pubE)"; priv="$(make_repo_on privE main)"; wt="$(release_wt privE)"
    before="$(head_of "${wt}")"
    echo "the gateway key rotates on Monday" > "${priv}/NO.RELEASE"
    git -C "${priv}" add NO.RELEASE
    git -C "${priv}" commit -qm "hold the private unit"
    run_release_units "${pub}" "${priv}" && rc=0 || rc=$?
    assert "exits nonzero"        "[ ${rc} -ne 0 ]"
    assert "private did not move" "[ \"$(head_of "${wt}")\" = \"${before}\" ]"
    assert "prints the reason"    "grep -q 'rotates on Monday' '${WORKROOT}/out'"
}

case_dry_run_reports_both_units() {
    bold "case: -n reports both units and moves neither"; echo
    local pub priv rc pub_before priv_before
    pub="$(make_repo pubF)"; priv="$(make_repo_on privF main)"
    pub_before="$(head_of "$(release_wt pubF)")"
    priv_before="$(head_of "$(release_wt privF)")"
    run_release_units "${pub}" "${priv}" -n && rc=0 || rc=$?
    assert "exits 0"            "[ ${rc} -eq 0 ]"
    assert "public unchanged"   "[ \"$(head_of "$(release_wt pubF)")\" = \"${pub_before}\" ]"
    assert "private unchanged"  "[ \"$(head_of "$(release_wt privF)")\" = \"${priv_before}\" ]"
    local reported
    reported="$(grep -c 'would release' "${WORKROOT}/out" || true)"
    assert "mentions both trees" "[ \"${reported}\" -eq 2 ]"
}

case_unit_selection_limits_the_run() {
    bold "case: -u names the only unit to release"; echo
    local pub priv rc priv_before
    pub="$(make_repo pubG)"; priv="$(make_repo_on privG main)"
    priv_before="$(head_of "$(release_wt privG)")"
    run_release_units "${pub}" "${priv}" -u public && rc=0 || rc=$?
    assert "exits 0"           "[ ${rc} -eq 0 ]"
    assert "public advanced"   \
        "[ \"$(head_of "$(release_wt pubG)")\" = \"$(git -C "${pub}" rev-parse master)\" ]"
    assert "private untouched" "[ \"$(head_of "$(release_wt privG)")\" = \"${priv_before}\" ]"
}


case_a_later_units_refusal_moves_nothing() {
    bold "case: a refusal in any unit releases none of them"; echo
    local pub priv pub_wt priv_wt rc pub_before priv_before
    pub="$(make_repo pubH)"; priv="$(make_repo_on privH main)"
    pub_wt="$(release_wt pubH)"; priv_wt="$(release_wt privH)"
    pub_before="$(head_of "${pub_wt}")"
    priv_before="$(head_of "${priv_wt}")"
    # The public unit is releasable; the private one is not.
    echo scribble >> "${priv_wt}/f"
    run_release_units "${pub}" "${priv}" && rc=0 || rc=$?
    assert "exits nonzero"        "[ ${rc} -ne 0 ]"
    assert "private did not move" "[ \"$(head_of "${priv_wt}")\" = \"${priv_before}\" ]"
    assert "public did not move either -- checked before anything advances" \
        "[ \"$(head_of "${pub_wt}")\" = \"${pub_before}\" ]"
}

case_a_later_units_sentry_moves_nothing() {
    bold "case: a sentry on the private unit holds the public one too"; echo
    local pub priv pub_wt rc pub_before
    pub="$(make_repo pubI)"; priv="$(make_repo_on privI main)"
    pub_wt="$(release_wt pubI)"
    pub_before="$(head_of "${pub_wt}")"
    echo "herd is mid-migration" > "${priv}/NO.RELEASE"
    git -C "${priv}" add NO.RELEASE
    git -C "${priv}" commit -qm hold
    run_release_units "${pub}" "${priv}" && rc=0 || rc=$?
    assert "exits nonzero"   "[ ${rc} -ne 0 ]"
    assert "public did not move" "[ \"$(head_of "${pub_wt}")\" = \"${pub_before}\" ]"
    assert "prints the reason"   "grep -q 'mid-migration' '${WORKROOT}/out'"
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
    case_sentry_blocks_release
    case_sentry_blocks_dry_run
    case_sentry_removed_releases
    case_sentry_checked_on_target_not_current
    case_empty_sentry_blocks_release
    case_whitespace_sentry_blocks_release
    case_private_unit_advances
    case_absent_private_unit_is_a_skip
    case_private_unit_without_a_release_worktree_is_a_skip
    case_dirty_private_unit_refused
    case_private_sentry_blocks_its_own_unit
    case_dry_run_reports_both_units
    case_unit_selection_limits_the_run
    case_a_later_units_refusal_moves_nothing
    case_a_later_units_sentry_moves_nothing
    echo
    printf 'ran %d, passed %d, failed %d\n' "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
