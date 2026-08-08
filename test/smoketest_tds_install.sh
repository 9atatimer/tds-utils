#!/usr/bin/env bash
# smoketest_tds_install.sh -- behavioral smoke test for bin/tds-install
# (also shipped inside artifacts as install.sh).
#
# Hermetic: artifacts are exported from a synthetic mini-repo and installed
# into a throwaway HOME (mktemp), never the real one. Covers: happy-path
# install (copy, BINS, INSTALL hook, VERIFY, current flip, $HOME links,
# log), VERIFY-failure abort, version flip + rollback, prune-to-3,
# regular-file link safety, and the UVTOOLS phase-5 stub failing loudly.
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
    bold "install: prune to 3 versions"; printf '\n'
    local root="$1" home t i
    home="$(fresh_home prune)"
    for i in 1 2 3 4; do
        t="$(export_one "${root}" "${root}/manifests/good.manifest" "${WORKROOT}/outD")"
        HOME="${home}" "${INSTALLER}" -a "${t}" >/dev/null 2>&1
    done
    local count
    count="$(find "${home}/.tds/dist" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
    assert "at most 3 version dirs kept" "[ '${count}' -le 3 ]"
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
    bold "install: services (systemd, opt-in)"; printf '\n'
    local root="$1" home tarball rc=0 fakebin="${WORKROOT}/fakebin-svc"
    home="$(fresh_home svc)"

    mkdir -p "${root}/units"
    printf '[Unit]\nDescription=delta test unit\n' > "${root}/units/delta.service"
    cat > "${root}/packages/delta.pkg" <<'EOF'
NAME=delta
PATHS="units/delta.service"
SERVICES="units/delta.service"
EOF
    cat > "${root}/manifests/svc.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="delta"
EOF
    git -C "${root}" -c user.email=t@t -c user.name=t add -A
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qm svc
    tarball="$(export_one "${root}" "${root}/manifests/svc.manifest" "${WORKROOT}/outH")"

    mkdir -p "${fakebin}"
    cat > "${fakebin}/systemctl" <<EOF
#!/bin/sh
echo "\$@" >> "${WORKROOT}/systemctl-calls.log"
exit 0
EOF
    chmod +x "${fakebin}/systemctl"

    # without -S: unit must NOT be registered
    HOME="${home}" PATH="${fakebin}:${PATH}" "${INSTALLER}" -a "${tarball}" \
        >/dev/null 2>&1 || rc=$?
    assert "install without -S succeeds"      "[ ${rc} -eq 0 ]"
    assert "no unit registered without -S"    "[ ! -e '${home}/.config/systemd/user/delta.service' ]"

    rc=0
    home="$(fresh_home svc2)"
    HOME="${home}" PATH="${fakebin}:${PATH}" "${INSTALLER}" -a "${tarball}" -S \
        >/dev/null 2>&1 || rc=$?
    assert "install with -S succeeds"         "[ ${rc} -eq 0 ]"
    assert "unit copied into systemd user dir" \
        "[ -f '${home}/.config/systemd/user/delta.service' ]"
    assert "systemctl enable called" \
        "grep -q 'enable --now delta.service' '${WORKROOT}/systemctl-calls.log'"
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
