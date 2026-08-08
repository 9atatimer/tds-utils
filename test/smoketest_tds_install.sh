#!/usr/bin/env bash
# smoketest_tds_install.sh -- behavioral smoke test for bin/tds-install
# (also shipped inside artifacts as install.sh).
#
# Hermetic: artifacts are exported from a synthetic mini-repo and installed
# into a throwaway HOME (mktemp), never the real one. Covers: happy-path
# install (copy, BINS, INSTALL hook, VERIFY, current flip, $HOME links,
# log), VERIFY-failure abort, version flip + rollback, prune-to-3 (which
# must never remove the active version, even when newer-named dirs
# outrank it), regular-file link safety, the UVTOOLS phase-5 stub, and
# platform-aware SERVICES registration (-S opt-in; the native unit type
# registers via a fake registrar, the foreign type skips with a note).
#
# Usage: ./test/smoketest_tds_install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
EXPORTER="${REPO_DIR}/bin/tds-export"
INSTALLER="${REPO_DIR}/bin/tds-install"

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

setup()   { WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/tds-install-test.XXXXXX")"; }
cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixtures ---

build_fixture_repo() {
    local root="${WORKROOT}/fixture-repo"
    mkdir -p "${root}"/{alpha,dotfiles,beta,gamma,packages,manifests,test}

    echo "rc v1"        > "${root}/dotfiles/rc"
    echo "beta content" > "${root}/beta/file.txt"
    echo "gamma"        > "${root}/gamma/file.txt"
    printf '#!/bin/sh\necho tool\n' > "${root}/alpha/tool"
    chmod +x "${root}/alpha/tool"
    printf '#!/bin/sh\ntouch "${TDS_INSTALL_ROOT}/.hook-ran"\n' > "${root}/alpha/setup.sh"
    chmod +x "${root}/alpha/setup.sh"
    printf '#!/bin/sh\nexit 0\n' > "${root}/test/smoke_alpha"
    printf '#!/bin/sh\necho boom >&2\nexit 1\n' > "${root}/test/smoke_beta"
    chmod +x "${root}/test/smoke_alpha" "${root}/test/smoke_beta"

    cat > "${root}/packages/alpha.pkg" <<'EOF'
NAME=alpha
PATHS="alpha dotfiles/rc"
LINKS="~/.alpharc:dotfiles/rc"
BINS="alpha/tool"
INSTALL=alpha/setup.sh
VERIFY=test/smoke_alpha
EOF
    cat > "${root}/packages/beta.pkg" <<'EOF'
NAME=beta
PATHS="beta"
VERIFY=test/smoke_beta
EOF
    cat > "${root}/packages/gamma.pkg" <<'EOF'
NAME=gamma
PATHS="gamma"
UVTOOLS="gamma"
EOF

    cat > "${root}/manifests/good.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="alpha"
EOF
    cat > "${root}/manifests/bad.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="alpha beta"
EOF
    cat > "${root}/manifests/uv.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="gamma"
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

# --- Test groups ---

test_install_happy() {
    bold "install: happy path"; printf '\n'
    local root="$1" home tarball rc=0
    home="$(fresh_home happy)"
    tarball="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outA")"

    HOME="${home}" "${INSTALLER}" -a "${tarball}" >/dev/null 2>&1 || rc=$?
    assert "install from tarball succeeds"  "[ ${rc} -eq 0 ]"

    local dist="${home}/.tds/dist"
    local cur="${dist}/current"
    assert "current symlink exists"         "[ -L '${cur}' ]"
    assert "current resolves into a version" "[ -f '${cur}/dotfiles/rc' ]"
    assert "HOME link created"              "[ -L '${home}/.alpharc' ]"
    assert "HOME link routes through current" \
        "readlink '${home}/.alpharc' | grep -q '/current/'"
    assert "HOME link readable"             "grep -q 'rc v1' '${home}/.alpharc'"
    assert "BINS symlinked into bin/"       "[ -x '${cur}/bin/tool' ]"
    assert "INSTALL hook ran"               "[ -e '${cur}/.hook-ran' ]"
    assert "install logged"                 "grep -q install '${dist}/log'"

    rc=0
    HOME="${home}" "${INSTALLER}" -a "${tarball}" >/dev/null 2>&1 || rc=$?
    assert "re-install same artifact idempotent" "[ ${rc} -eq 0 ]"
}

test_verify_abort() {
    bold "install: VERIFY failure aborts"; printf '\n'
    local root="$1" home tarball rc=0
    home="$(fresh_home verify)"
    tarball="$(export_one "${root}" "${root}/manifests/bad.manifest" "${WORKROOT}/outB")"

    HOME="${home}" "${INSTALLER}" -a "${tarball}" >/dev/null 2>&1 || rc=$?
    assert "failing VERIFY fails install"     "[ ${rc} -ne 0 ]"
    assert "no current after rejected stage"  "[ ! -e '${home}/.tds/dist/current' ]"
    assert "rejected staging removed" \
        "[ \"\$(ls '${home}/.tds/dist' 2>/dev/null | grep -cv '^log\$' || true)\" = 0 ]"
    assert "no HOME link after reject"        "[ ! -e '${home}/.alpharc' ]"
}

test_flip_rollback() {
    bold "install: flip + rollback"; printf '\n'
    local root="$1" home t1 t2 rc=0 v1
    home="$(fresh_home flip)"
    t1="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outC")"
    HOME="${home}" "${INSTALLER}" -a "${t1}" >/dev/null 2>&1
    v1="$(readlink "${home}/.tds/dist/current")"

    echo "rc v2" > "${root}/dotfiles/rc"
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qam v2
    t2="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outC")"

    HOME="${home}" "${INSTALLER}" -a "${t2}" >/dev/null 2>&1 || rc=$?
    assert "second version installs"   "[ ${rc} -eq 0 ]"
    assert "current flipped"           "[ \"\$(readlink '${home}/.tds/dist/current')\" != '${v1}' ]"
    assert "link sees new content"     "grep -q 'rc v2' '${home}/.alpharc'"

    rc=0
    HOME="${home}" "${INSTALLER}" --rollback >/dev/null 2>&1 || rc=$?
    assert "rollback succeeds"         "[ ${rc} -eq 0 ]"
    assert "current back to v1"        "[ \"\$(readlink '${home}/.tds/dist/current')\" = '${v1}' ]"
    assert "link sees old content"     "grep -q 'rc v1' '${home}/.alpharc'"

    git -C "${root}" checkout -q master~1 -- dotfiles/rc 2>/dev/null || true
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qam restore || true
}

test_prune() {
    bold "install: prune to 3 versions (numeric .n ordering)"; printf '\n'
    local root="$1" home t i vbase dist count
    home="$(fresh_home prune)"
    vbase="v$(git -C "${root}" log -1 --format=%cs | tr - .)"
    # 10 same-day exports produce ${vbase}, ${vbase}.2 .. ${vbase}.10; the
    # .10 suffix must outrank .2-.9 numerically -- a lexical sort would
    # order .10 below .2 and prune the just-installed newest version
    for i in 1 2 3 4 5 6 7 8 9 10; do
        t="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outD")"
        HOME="${home}" "${INSTALLER}" -a "${t}" >/dev/null 2>&1
    done
    dist="${home}/.tds/dist"
    count="$(find "${dist}" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
    assert "exactly 3 version dirs kept" "[ '${count}' -eq 3 ]"
    assert "newest .10 kept"             "[ -d '${dist}/${vbase}.10' ]"
    assert ".9 kept"                     "[ -d '${dist}/${vbase}.9' ]"
    assert ".8 kept"                     "[ -d '${dist}/${vbase}.8' ]"
    assert ".7 pruned"                   "[ ! -e '${dist}/${vbase}.7' ]"
    assert "current points at .10" \
        "[ \"\$(basename \"\$(readlink '${dist}/current')\")\" = '${vbase}.10' ]"
}

test_prune_keeps_active() {
    bold "install: prune never removes the active version"; printf '\n'
    local root="$1" home t dist cur rc=0
    home="$(fresh_home pruneactive)"
    t="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outI")"
    HOME="${home}" "${INSTALLER}" -a "${t}" >/dev/null 2>&1
    dist="${home}/.tds/dist"
    cur="$(readlink "${dist}/current")"
    # stage three newer-named version dirs, then re-install the same older
    # artifact (downgrade/re-seed): the active dir ranks 4th by calver, so
    # an unguarded prune would delete it and leave current dangling
    mkdir "${dist}/v2999.01.01" "${dist}/v2999.01.02" "${dist}/v2999.01.03"
    HOME="${home}" "${INSTALLER}" -a "${t}" >/dev/null 2>&1 || rc=$?
    assert "re-install over newer staged dirs succeeds" "[ ${rc} -eq 0 ]"
    assert "active version dir survives prune" "[ -d '${cur}' ]"
    assert "current still resolves"    "[ -f '${dist}/current/dotfiles/rc' ]"
    assert "HOME link still readable"  "grep -q 'rc v1' '${home}/.alpharc'"
}

test_link_safety() {
    bold "install: link safety"; printf '\n'
    local root="$1" home tarball rc=0
    home="$(fresh_home safety)"
    echo "precious user data" > "${home}/.alpharc"
    tarball="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outE")"
    HOME="${home}" "${INSTALLER}" -a "${tarball}" >/dev/null 2>&1 || rc=$?
    assert "install still succeeds"      "[ ${rc} -eq 0 ]"
    assert "regular file NOT clobbered"  "grep -q precious '${home}/.alpharc'"
    # capture, don't pipe: grep -q + pipefail would EPIPE the installer
    local rerun_out
    rerun_out="$(HOME="${home}" "${INSTALLER}" -a "${tarball}" 2>&1 || true)"
    assert "clobber skip logged as warning" "grep -qi skip <<<\"\${rerun_out}\""
}

test_embedded_installer() {
    bold "install: embedded install.sh (work-machine path)"; printf '\n'
    local root="$1" home tarball unpack rc=0
    home="$(fresh_home embedded)"
    tarball="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outG")"
    unpack="${WORKROOT}/unpackG"
    mkdir -p "${unpack}"
    tar -xzf "${tarball}" -C "${unpack}"
    ( cd "${unpack}"/tds-env-* && HOME="${home}" ./install.sh ) >/dev/null 2>&1 || rc=$?
    assert "./install.sh from artifact dir succeeds" "[ ${rc} -eq 0 ]"
    assert "current active"    "[ -f '${home}/.tds/dist/current/dotfiles/rc' ]"
    assert "HOME link created" "[ -L '${home}/.alpharc' ]"
}

test_uvtools() {
    bold "install: uvtools"; printf '\n'
    local root="$1" home tarball rc=0 fakebin="${WORKROOT}/fakebin"
    home="$(fresh_home uv)"
    tarball="$(export_one "${root}" "${root}/manifests/uv.manifest" "${WORKROOT}/outF")"

    mkdir -p "${fakebin}"
    cat > "${fakebin}/uv" <<EOF
#!/bin/sh
echo "\$@" >> "${WORKROOT}/uv-calls.log"
exit 0
EOF
    chmod +x "${fakebin}/uv"

    HOME="${home}" PATH="${fakebin}:${PATH}" "${INSTALLER}" -a "${tarball}" \
        >/dev/null 2>&1 || rc=$?
    assert "UVTOOLS install succeeds with uv present" "[ ${rc} -eq 0 ]"
    assert "uv tool install called on shipped tree" \
        "grep -q 'tool install .*gamma' '${WORKROOT}/uv-calls.log'"

    rc=0
    HOME="$(fresh_home uv2)" TDS_UV=/nonexistent-uv "${INSTALLER}" -a "${tarball}" \
        >/dev/null 2>&1 || rc=$?
    assert "UVTOOLS fails loudly without uv" "[ ${rc} -ne 0 ]"
}

test_services() {
    bold "install: services (platform-aware, opt-in)"; printf '\n'
    local root="$1" home tarball rc=0 fakebin="${WORKROOT}/fakebin-svc"
    local os native_unit native_call native_log foreign_unit foreign_log
    local skip_note noflag_out svc_out
    os="$(uname -s)"

    # fixture package delta ships BOTH unit flavors: run_services must
    # register only the unit native to the running OS and skip the
    # foreign one with a note (never a failure)
    mkdir -p "${root}/units"
    printf '[Unit]\nDescription=delta test unit\n' > "${root}/units/delta.service"
    printf '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict/></plist>\n' \
        > "${root}/units/delta.plist"
    cat > "${root}/packages/delta.pkg" <<'EOF'
NAME=delta
PATHS="units"
SERVICES="units/delta.service units/delta.plist"
EOF
    cat > "${root}/manifests/svc.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="delta"
EOF
    git -C "${root}" -c user.email=t@t -c user.name=t add -A
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qm svc
    tarball="$(export_one "${root}" "${root}/manifests/svc.manifest" "${WORKROOT}/outH")"

    # fake BOTH registrars on PATH; only the native one may ever be invoked
    mkdir -p "${fakebin}"
    cat > "${fakebin}/systemctl" <<EOF
#!/bin/sh
echo "\$@" >> "${WORKROOT}/systemctl-calls.log"
exit 0
EOF
    cat > "${fakebin}/launchctl" <<EOF
#!/bin/sh
echo "\$@" >> "${WORKROOT}/launchctl-calls.log"
exit 0
EOF
    chmod +x "${fakebin}/systemctl" "${fakebin}/launchctl"

    if [ "${os}" = "Darwin" ]; then
        native_unit="Library/LaunchAgents/delta.plist"
        native_call="bootstrap gui/.*delta.plist"
        native_log="${WORKROOT}/launchctl-calls.log"
        foreign_unit=".config/systemd/user/delta.service"
        foreign_log="${WORKROOT}/systemctl-calls.log"
        skip_note="delta.service: systemd unit on Darwin, skipping"
    else
        native_unit=".config/systemd/user/delta.service"
        native_call="enable --now delta.service"
        native_log="${WORKROOT}/systemctl-calls.log"
        foreign_unit="Library/LaunchAgents/delta.plist"
        foreign_log="${WORKROOT}/launchctl-calls.log"
        skip_note="delta.plist: launchd unit on ${os}, skipping"
    fi

    # without -S: registration is strictly opt-in, neither unit may register
    home="$(fresh_home svc)"
    noflag_out="$(HOME="${home}" PATH="${fakebin}:${PATH}" \
        "${INSTALLER}" -a "${tarball}" 2>&1)" || rc=$?
    assert "install without -S succeeds"      "[ ${rc} -eq 0 ]"
    assert "opt-out noted without -S"         "grep -q 'S not given; skipping' <<<\"\${noflag_out}\""
    assert "no systemd unit without -S"       "[ ! -e '${home}/.config/systemd/user/delta.service' ]"
    assert "no launchd unit without -S"       "[ ! -e '${home}/Library/LaunchAgents/delta.plist' ]"

    # with -S: native unit registers, foreign unit skips with a note
    rc=0
    home="$(fresh_home svc2)"
    svc_out="$(HOME="${home}" PATH="${fakebin}:${PATH}" \
        "${INSTALLER}" -a "${tarball}" -S 2>&1)" || rc=$?
    assert "install with -S succeeds"         "[ ${rc} -eq 0 ]"
    assert "native unit copied into user dir" "[ -f '${home}/${native_unit}' ]"
    assert "native registrar call recorded"   "grep -q '${native_call}' '${native_log}'"
    assert "foreign unit skip noted"          "grep -q '${skip_note}' <<<\"\${svc_out}\""
    assert "foreign unit NOT copied"          "[ ! -e '${home}/${foreign_unit}' ]"
    assert "foreign registrar never invoked"  "[ ! -e '${foreign_log}' ]"
}

# --- Flow ---

run_all() {
    setup
    local root
    root="$(build_fixture_repo)"
    test_install_happy "${root}"
    test_verify_abort "${root}"
    test_flip_rollback "${root}"
    test_prune "${root}"
    test_prune_keeps_active "${root}"
    test_link_safety "${root}"
    test_embedded_installer "${root}"
    test_uvtools "${root}"
    test_services "${root}"
    printf '\n'
    bold "results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    printf '\n'
    [ "${TESTS_FAILED}" -eq 0 ]
}

# --- Main ---

main() { run_all; }
main "$@"
