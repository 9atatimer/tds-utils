#!/usr/bin/env bash
# smoketest_tds_publish.sh -- behavioral smoke test for tds-export -r
# (gpg sign+encrypt to the manifest's GPGKEY, neutral slug, gh release).
#
# Hermetic: scratch GNUPGHOME with a throwaway no-protection keypair; `gh`
# is a fake on PATH that records its argv. Round-trips the ciphertext
# through gpg --decrypt to prove signature + content survive.
#
# Usage: ./test/smoketest_tds_publish.sh

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

setup()   { WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/tds-publish-test.XXXXXX")"; }
cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixtures ---

make_keypair() {
    # scratch no-protection key in GNUPGHOME (exported by run_all -- this
    # function runs in a command substitution, so it cannot export itself);
    # prints the key fingerprint
    mkdir -p "${GNUPGHOME}"
    chmod 700 "${GNUPGHOME}"
    # default/default: primary sign key + encryption subkey (ed25519 alone
    # cannot encrypt)
    gpg --batch --quiet --passphrase '' --quick-generate-key \
        "work-instance@test.invalid" default default never 2>/dev/null
    gpg --batch --list-keys --with-colons "work-instance@test.invalid" \
        | awk -F: '/^fpr:/ { print $10; exit }'
}

make_fake_gh() {
    local bindir="${WORKROOT}/fakebin"
    mkdir -p "${bindir}"
    cat > "${bindir}/gh" <<EOF
#!/bin/sh
echo "\$@" >> "${WORKROOT}/gh-calls.log"
exit 0
EOF
    chmod +x "${bindir}/gh"
    printf '%s\n' "${bindir}"
}

build_fixture_repo() {
    local root="${WORKROOT}/fixture-repo" keyid="$1"
    mkdir -p "${root}"/{alpha,packages,manifests}
    echo "alpha content" > "${root}/alpha/file.txt"
    cat > "${root}/packages/alpha.pkg" <<'EOF'
NAME=alpha
PATHS="alpha"
EOF
    cat > "${root}/manifests/work.manifest" <<EOF
DEVICE=workbox
GPGKEY=${keyid}
PACKAGES="alpha"
EOF
    cat > "${root}/manifests/nokey.manifest" <<'EOF'
DEVICE=workbox
PACKAGES="alpha"
EOF
    git -C "${root}" init -q
    git -C "${root}" symbolic-ref HEAD refs/heads/master
    git -C "${root}" -c user.email=t@t -c user.name=t add -A
    git -C "${root}" -c user.email=t@t -c user.name=t commit -qm fixture
    printf '%s\n' "${root}"
}

# --- Test groups ---

test_publish() {
    bold "publish: -r sign + encrypt + release"; printf '\n'
    local root="$1" out="${WORKROOT}/out" rc=0
    PATH="${FAKEBIN}:${PATH}" "${EXPORTER}" -C "${root}" \
        -m "${root}/manifests/work.manifest" -o "${out}" -r >/dev/null 2>&1 || rc=$?
    assert "publish export succeeds" "[ ${rc} -eq 0 ]"

    local cipher
    cipher="$(ls "${out}"/*.tar.gz.gpg 2>/dev/null | head -1 || true)"
    assert "ciphertext artifact produced"    "[ -n '${cipher}' ]"
    [ -n "${cipher}" ] || return 0
    assert "asset name is neutral (no device)" "! basename '${cipher}' | grep -q workbox"
    assert "asset name carries version"        "basename '${cipher}' | grep -q 'v20[0-9.]*\\.tar\\.gz\\.gpg'"

    assert "gh release created with env-<ver> tag" \
        "grep -q 'release create env-v' '${WORKROOT}/gh-calls.log'"
    assert "only ciphertext uploaded" \
        "! grep -E '[^ ]+\\.tar\\.gz( |\$)' '${WORKROOT}/gh-calls.log' | grep -qv '\\.gpg'"
    assert "no device name in release invocation" \
        "! grep -q workbox '${WORKROOT}/gh-calls.log'"
}

test_roundtrip() {
    bold "publish: decrypt round-trip"; printf '\n'
    local out="${WORKROOT}/out" cipher plain listing rc=0
    cipher="$(ls "${out}"/*.tar.gz.gpg | head -1)"
    plain="${WORKROOT}/roundtrip.tar.gz"
    gpg --batch --quiet --decrypt "${cipher}" > "${plain}" 2>"${WORKROOT}/gpg-verify.log" || rc=$?
    assert "decrypt succeeds"            "[ ${rc} -eq 0 ]"
    assert "signature verified"          "grep -qi 'signature' '${WORKROOT}/gpg-verify.log'"
    listing="$(tar -tzf "${plain}")"
    assert "decrypted tarball intact"    "grep -q 'alpha/file.txt\$' <<<\"\${listing}\""
    assert "installer aboard"            "grep -q 'install.sh\$' <<<\"\${listing}\""
}

test_publish_guards() {
    bold "publish: guards"; printf '\n'
    local root="$1" rc=0
    PATH="${FAKEBIN}:${PATH}" "${EXPORTER}" -C "${root}" \
        -m "${root}/manifests/nokey.manifest" -o "${WORKROOT}/out2" -r \
        >/dev/null 2>&1 || rc=$?
    assert "-r without GPGKEY fails" "[ ${rc} -ne 0 ]"
    rc=0
    "${EXPORTER}" -C "${root}" -m "${root}/manifests/nokey.manifest" \
        -o "${WORKROOT}/out3" >/dev/null 2>&1 || rc=$?
    assert "local export without GPGKEY still fine" "[ ${rc} -eq 0 ]"
}

# --- Flow ---

run_all() {
    setup
    local keyid root
    export GNUPGHOME="${WORKROOT}/gnupg"
    keyid="$(make_keypair)"
    [ -n "${keyid}" ] || { echo "could not create scratch gpg key" >&2; exit 1; }
    FAKEBIN="$(make_fake_gh)"
    root="$(build_fixture_repo "${keyid}")"
    test_publish "${root}"
    test_roundtrip
    test_publish_guards "${root}"
    printf '\n'
    bold "results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    printf '\n'
    [ "${TESTS_FAILED}" -eq 0 ]
}

# --- Main ---

main() { run_all; }
main "$@"
