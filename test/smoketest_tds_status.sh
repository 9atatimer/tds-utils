#!/usr/bin/env bash
# smoketest_tds_status.sh -- behavioral smoke test for bin/tds-status.
#
# Hermetic: artifacts are exported from a synthetic mini-repo and installed
# into a throwaway HOME (mktemp), never the real one. Covers: clean install
# (exit 0, reports the current version, writes nothing), retargeted and
# deleted $HOME links (nonzero, names the link), a newer version dir staged
# but not active (nonzero; the .n calver suffix must compare numerically,
# not lexically), install + rollback history echoed from the log, and the
# no-install-at-all case (plain report, exit 0 -- nonzero only when stale
# tds links remain in $HOME).
#
# Usage: ./test/smoketest_tds_status.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
EXPORTER="${REPO_DIR}/bin/tds-export"
INSTALLER="${REPO_DIR}/bin/tds-install"
STATUS="${REPO_DIR}/bin/tds-status"

# --- Test harness ---

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

setup()   { WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/tds-status-test.XXXXXX")"; }
cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixtures ---

build_fixture_repo() {
    local root="${WORKROOT}/fixture-repo"
    mkdir -p "${root}"/{alpha,dotfiles,packages,manifests}

    echo "rc v1"         > "${root}/dotfiles/rc"
    echo "alpha content" > "${root}/alpha/file.txt"

    cat > "${root}/packages/alpha.pkg" <<'EOF'
NAME=alpha
PATHS="alpha dotfiles/rc"
LINKS="~/.alpharc:dotfiles/rc"
EOF
    cat > "${root}/manifests/good.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="alpha"
EOF

    git -C "${root}" init -q
    git -C "${root}" symbolic-ref HEAD refs/heads/master
    git -C "${root}" -c user.email=t@t -c user.name=t add -A
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qm fixture
    printf '%s\n' "${root}"
}

export_one() {
    # export_one <root> <manifest> <outdir> -> prints tarball path
    "${EXPORTER}" -C "$1" -m "$2" -o "$3" >/dev/null
    ls -t "$3"/tds-env-*.tar.gz | head -1
}

fresh_home() {
    local h="${WORKROOT}/home-$1"
    mkdir -p "${h}"
    printf '%s\n' "${h}"
}

install_home() {
    # install_home <home> <tarball>
    HOME="$1" "${INSTALLER}" -a "$2" >/dev/null 2>&1
}

run_status() {
    # run_status <home> -> globals STATUS_RC / STATUS_OUT
    STATUS_RC=0
    STATUS_OUT="$(HOME="$1" "${STATUS}" 2>&1)" || STATUS_RC=$?
}

# --- Test groups ---

test_clean_install() {
    bold "status: clean install"; printf '\n'
    local root="$1" home tarball version before after
    home="$(fresh_home clean)"
    tarball="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outA")"
    install_home "${home}" "${tarball}"
    version="$(basename "$(readlink "${home}/.tds/dist/current")")"

    before="$(find "${home}/.tds/dist" | sort)"
    run_status "${home}"
    after="$(find "${home}/.tds/dist" | sort)"

    assert "bin/tds-status exists and is executable" "[ -x '${STATUS}' ]"
    assert "clean install exits 0"        "[ ${STATUS_RC} -eq 0 ]"
    assert "reports current version"      "grep -q '${version}' <<<\"\${STATUS_OUT}\""
    assert "writes nothing under distroot" "[ \"\${before}\" = \"\${after}\" ]"
}

test_retargeted_link() {
    bold "status: retargeted \$HOME link"; printf '\n'
    local root="$1" home tarball
    home="$(fresh_home retarget)"
    tarball="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outB")"
    install_home "${home}" "${tarball}"

    echo "elsewhere" > "${home}/elsewhere"
    rm "${home}/.alpharc"
    ln -s "${home}/elsewhere" "${home}/.alpharc"
    run_status "${home}"

    assert "retargeted link is drift"     "[ ${STATUS_RC} -ne 0 ]"
    assert "drift names the link"         "grep -q '\.alpharc' <<<\"\${STATUS_OUT}\""
}

test_deleted_link() {
    bold "status: deleted \$HOME link"; printf '\n'
    local root="$1" home tarball
    home="$(fresh_home deleted)"
    tarball="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outC")"
    install_home "${home}" "${tarball}"

    rm "${home}/.alpharc"
    run_status "${home}"

    assert "deleted link is drift"        "[ ${STATUS_RC} -ne 0 ]"
    assert "drift names the missing link" "grep -q '\.alpharc' <<<\"\${STATUS_OUT}\""
}

test_version_drift() {
    bold "status: newer version staged but not active"; printf '\n'
    local root="$1" home t1 t2 v1 v2 fake
    home="$(fresh_home version)"
    # same outdir on purpose: the second export collision-bumps to <base>.2
    t1="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outD")"
    t2="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outD")"
    install_home "${home}" "${t1}"
    v1="$(basename "$(readlink "${home}/.tds/dist/current")")"
    install_home "${home}" "${t2}"
    v2="$(basename "$(readlink "${home}/.tds/dist/current")")"

    run_status "${home}"
    assert "current-is-newest exits 0"    "[ ${STATUS_RC} -eq 0 ]"

    # <base>.10 sorts lexically BEFORE the active <base>.2 -- a lexical
    # comparison would call the active version newest and miss the drift
    fake="${v1}.10"
    mkdir "${home}/.tds/dist/${fake}"
    run_status "${home}"
    assert "newer staged dir is drift"    "[ ${STATUS_RC} -ne 0 ]"
    assert "drift names the newer version" "grep -q '${fake}' <<<\"\${STATUS_OUT}\""
    assert "active .2 beats lexical trap" "grep -q '${v2}' <<<\"\${STATUS_OUT}\""
}

test_history() {
    bold "status: install + rollback history"; printf '\n'
    local root="$1" home t1 t2 v1 v2
    home="$(fresh_home history)"
    t1="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outE")"
    t2="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outE")"
    install_home "${home}" "${t1}"
    v1="$(basename "$(readlink "${home}/.tds/dist/current")")"
    install_home "${home}" "${t2}"
    v2="$(basename "$(readlink "${home}/.tds/dist/current")")"
    HOME="${home}" "${INSTALLER}" --rollback >/dev/null 2>&1

    run_status "${home}"
    assert "history shows first install"  "grep -q 'install ${v1}' <<<\"\${STATUS_OUT}\""
    assert "history shows second install" "grep -q 'install ${v2}' <<<\"\${STATUS_OUT}\""
    assert "history shows rollback"       "grep -q 'rollback' <<<\"\${STATUS_OUT}\""
    # rolled back = not on the newest staged version: that IS version drift
    assert "rolled-back state is drift"   "[ ${STATUS_RC} -ne 0 ]"
}

test_no_install() {
    bold "status: no install at all"; printf '\n'
    local root="$1" home
    home="$(fresh_home none)"

    run_status "${home}"
    assert "no install exits 0"           "[ ${STATUS_RC} -eq 0 ]"
    assert "no install reported plainly"  "grep -qi 'no tds install' <<<\"\${STATUS_OUT}\""

    # a stale link into the (missing) distroot is drift even with no install
    ln -s "${home}/.tds/dist/current/dotfiles/rc" "${home}/.stalerc"
    run_status "${home}"
    assert "stale link without install is drift" "[ ${STATUS_RC} -ne 0 ]"
    assert "drift names the stale link"   "grep -q '\.stalerc' <<<\"\${STATUS_OUT}\""
}

# --- Flow ---

run_all() {
    setup
    local root
    root="$(build_fixture_repo)"
    test_clean_install "${root}"
    test_retargeted_link "${root}"
    test_deleted_link "${root}"
    test_version_drift "${root}"
    test_history "${root}"
    test_no_install "${root}"
    printf '\n'
    bold "results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    printf '\n'
    [ "${TESTS_FAILED}" -eq 0 ]
}

# --- Main ---

main() { run_all; }
main "$@"
