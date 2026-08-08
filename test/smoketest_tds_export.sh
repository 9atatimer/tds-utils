#!/usr/bin/env bash
# smoketest_tds_export.sh -- behavioral smoke test for bin/tds-export.
#
# Hermetic: exports run against synthetic mini-repos built in mktemp dirs
# (git init'd on master, committed clean), never against this checkout. The
# post-build deny scan is additionally unit-tested against a hand-crafted
# violating tarball, since a correct resolve step makes it unreachable
# end-to-end.
#
# Usage: ./test/smoketest_tds_export.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
EXPORTER="${REPO_DIR}/bin/tds-export"

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

setup()   { WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/tds-export-test.XXXXXX")"; }
cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixtures ---

# Build a synthetic source repo with packages alpha, beta (REQUIRES=secret),
# secret, and manifests exercising the deny paths. Prints the repo path.
build_fixture_repo() {
    local root="${WORKROOT}/fixture-repo"
    mkdir -p "${root}"/{alpha,beta,secret,packages,manifests,test}

    echo "alpha content"  > "${root}/alpha/file.txt"
    echo "beta content"   > "${root}/beta/file.txt"
    echo "SECRET"         > "${root}/secret/hidden.txt"
    printf '#!/bin/sh\nexit 0\n' > "${root}/test/smoke_alpha"
    chmod +x "${root}/test/smoke_alpha"

    cat > "${root}/packages/alpha.pkg" <<'EOF'
NAME=alpha
PATHS="alpha"
VERIFY=test/smoke_alpha
EOF
    cat > "${root}/packages/beta.pkg" <<'EOF'
NAME=beta
PATHS="beta"
REQUIRES="secret"
EOF
    cat > "${root}/packages/secret.pkg" <<'EOF'
NAME=secret
PATHS="secret"
EOF

    cat > "${root}/manifests/good.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="alpha"
DENY="secret"
EOF
    cat > "${root}/manifests/direct-deny.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="alpha secret"
DENY="secret"
EOF
    cat > "${root}/manifests/via-requires.manifest" <<'EOF'
DEVICE=devbox
PACKAGES="alpha beta"
DENY="secret"
EOF

    git -C "${root}" init -q
    git -C "${root}" symbolic-ref HEAD refs/heads/master
    git -C "${root}" -c user.email=t@t -c user.name=t add -A
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qm fixture
    printf '%s\n' "${root}"
}

# --- Test groups ---

test_good_export() {
    bold "export: happy path"; printf '\n'
    local root="$1" out="${WORKROOT}/out1" rc=0
    "${EXPORTER}" -C "${root}" -m "${root}/manifests/good.manifest" -o "${out}" \
        >/dev/null 2>&1 || rc=$?
    assert "clean export succeeds" "[ ${rc} -eq 0 ]"

    local tarball
    tarball="$(ls "${out}"/tds-env-devbox-v*.tar.gz 2>/dev/null | head -1 || true)"
    assert "artifact named tds-env-<device>-<version>" "[ -n '${tarball}' ]"
    [ -n "${tarball}" ] || return 0

    local listing
    listing="$(tar -tzf "${tarball}")"
    assert "package path shipped"      "grep -q 'alpha/file.txt\$' <<<\"\${listing}\""
    assert "VERIFY script auto-shipped" "grep -q 'test/smoke_alpha\$' <<<\"\${listing}\""
    assert "ARTIFACT-MANIFEST present" "grep -q 'ARTIFACT-MANIFEST\$' <<<\"\${listing}\""
    assert "denied package absent"     "! grep -q secret <<<\"\${listing}\""
    assert "no git history in artifact" "! grep -q '\\.git' <<<\"\${listing}\""

    local mdir="${WORKROOT}/m1"
    mkdir -p "${mdir}"
    tar -xzf "${tarball}" -C "${mdir}"
    local mf
    mf="$(find "${mdir}" -name ARTIFACT-MANIFEST | head -1)"
    # shellcheck source=../lib/tds-dist.sh
    source "${REPO_DIR}/lib/tds-dist.sh"
    assert "manifest DEVICE recorded"   "[ \"\$(tds_dist_get '${mf}' DEVICE)\" = devbox ]"
    assert "manifest PACKAGES recorded" "[ \"\$(tds_dist_get '${mf}' PACKAGES)\" = alpha ]"
    assert "manifest sha recorded"      "[ \"\$(tds_dist_get '${mf}' SOURCE_SHA)\" = \"\$(git -C '${root}' rev-parse HEAD)\" ]"

    rc=0
    "${EXPORTER}" -C "${root}" -m "${root}/manifests/good.manifest" -o "${out}" \
        >/dev/null 2>&1 || rc=$?
    assert "re-export succeeds"         "[ ${rc} -eq 0 ]"
    assert "collision bumps version"    "ls '${out}' | grep -q '\\.2\\.tar\\.gz'"
}

test_deny() {
    bold "export: deny enforcement"; printf '\n'
    local root="$1" out="${WORKROOT}/out2" rc
    rc=0; "${EXPORTER}" -C "${root}" -m "${root}/manifests/direct-deny.manifest" \
        -o "${out}" >/dev/null 2>&1 || rc=$?
    assert "direct deny violation fails"      "[ ${rc} -ne 0 ]"
    rc=0; "${EXPORTER}" -C "${root}" -m "${root}/manifests/via-requires.manifest" \
        -o "${out}" >/dev/null 2>&1 || rc=$?
    assert "deny via REQUIRES fails"          "[ ${rc} -ne 0 ]"
    rc=0; "${EXPORTER}" -C "${root}" -m "${root}/manifests/good.manifest" \
        -o "${out}" -p secret >/dev/null 2>&1 || rc=$?
    assert "-p of denied package fails"       "[ ${rc} -ne 0 ]"
    rc=0; "${EXPORTER}" -C "${root}" -m "${root}/manifests/good.manifest" \
        -o "${out}" -p alpha >/dev/null 2>&1 || rc=$?
    assert "-p of allowed package succeeds"   "[ ${rc} -eq 0 ]"
}

test_tree_state() {
    bold "export: source tree gating"; printf '\n'
    local root="$1" out="${WORKROOT}/out3" rc
    echo dirty >> "${root}/alpha/file.txt"
    rc=0; "${EXPORTER}" -C "${root}" -m "${root}/manifests/good.manifest" \
        -o "${out}" >/dev/null 2>&1 || rc=$?
    assert "dirty tree fails"        "[ ${rc} -ne 0 ]"
    git -C "${root}" checkout -q -- alpha/file.txt

    git -C "${root}" checkout -qb sidebranch
    rc=0; "${EXPORTER}" -C "${root}" -m "${root}/manifests/good.manifest" \
        -o "${out}" >/dev/null 2>&1 || rc=$?
    assert "non-master branch fails" "[ ${rc} -ne 0 ]"
    git -C "${root}" checkout -q master
}

test_ownership_gate() {
    bold "export: ownership gating"; printf '\n'
    local root="$1" out="${WORKROOT}/out4" rc
    cat > "${root}/packages/grabby.pkg" <<'EOF'
NAME=grabby
PATHS="alpha/file.txt"
EOF
    git -C "${root}" -c user.email=t@t -c user.name=t add -A
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qm grabby
    rc=0; "${EXPORTER}" -C "${root}" -m "${root}/manifests/good.manifest" \
        -o "${out}" >/dev/null 2>&1 || rc=$?
    assert "duplicate path claim fails export" "[ ${rc} -ne 0 ]"
    git -C "${root}" rm -q packages/grabby.pkg
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qm rmgrabby
}

test_deny_scan_unit() {
    bold "export: post-build deny scan (unit)"; printf '\n'
    local root="$1" rc
    # Hand-craft a violating tarball: contains a path owned by pkg "secret".
    local bad="${WORKROOT}/bad-artifact"
    mkdir -p "${bad}/tds-env-devbox-v1/secret"
    echo leak > "${bad}/tds-env-devbox-v1/secret/hidden.txt"
    tar -czf "${WORKROOT}/bad.tar.gz" -C "${bad}" tds-env-devbox-v1

    # shellcheck source=../bin/tds-export
    source "${EXPORTER}"
    # subshells: scan_artifact's die() exits, which must not kill this test
    rc=0; ( scan_artifact "${WORKROOT}/bad.tar.gz" "${root}" "secret" ) \
        >/dev/null 2>&1 || rc=$?
    assert "scan flags denied path in tarball" "[ ${rc} -ne 0 ]"
    rc=0; ( scan_artifact "${WORKROOT}/bad.tar.gz" "${root}" "" ) \
        >/dev/null 2>&1 || rc=$?
    assert "scan passes with empty deny list"  "[ ${rc} -eq 0 ]"
}

# --- Flow ---

run_all() {
    setup
    local root
    root="$(build_fixture_repo)"
    test_good_export "${root}"
    test_deny "${root}"
    test_tree_state "${root}"
    test_ownership_gate "${root}"
    test_deny_scan_unit "${root}"
    printf '\n'
    bold "results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    printf '\n'
    [ "${TESTS_FAILED}" -eq 0 ]
}

# --- Main ---

main() { run_all; }
main "$@"
