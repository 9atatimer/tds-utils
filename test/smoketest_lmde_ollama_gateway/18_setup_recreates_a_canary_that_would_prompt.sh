#!/usr/bin/env bash
# 18_setup_recreates_a_canary_that_would_prompt.sh
# Given a keychain canary left by an earlier install whose access list
# admits only /usr/bin/security (so the probe's Security framework check,
# run from /usr/bin/python3, could read it only through a Keychain dialog),
# When setup.sh installs, Then it replaces the canary with one any
# application may read without a dialog -- one item, same service, the
# non-secret value -- so re-running setup.sh is the fix the probe names
# (tds-utils Issue#441).
#
# Asserted from the item's access list (security dump-keychain -a, which
# reads no secret), never by reading the stale item from python: that read
# is the one that would prompt.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

# canary_decrypt_apps -- the "applications" line of the canary's decrypt
# entry, one line per canary item in the keychain.
canary_decrypt_apps() {
    security dump-keychain -a "${KEYCHAIN}" 2>/dev/null | awk -v svc="${CANARY_SERVICE}" '
        /^keychain:/ { in_canary = 0; want = 0 }
        index($0, "\"svce\"<blob>=\"" svc "\"") { in_canary = 1 }
        in_canary && /authorizations .*decrypt/ { want = 1; next }
        in_canary && want && /applications/ { sub(/^ +/, ""); print; want = 0 }
    '
}

main() {
    require_macos
    fixture_setup
    install_fake_launchctl
    security delete-generic-password -s "${CANARY_SERVICE}" "${KEYCHAIN}" >/dev/null 2>&1
    security add-generic-password -s "${CANARY_SERVICE}" -a ollama-gateway \
        -w "not-a-secret" "${KEYCHAIN}" >/dev/null
    assert_eq "$(canary_decrypt_apps)" "applications (1):" "fixture: the stale canary admits only security"

    local out
    out="$(run_setup)" || fail "install failed: ${out}"

    assert_eq "$(canary_decrypt_apps)" "applications: <null>" "the canary now admits any application without a dialog"
    assert_eq "$(security find-generic-password -s "${CANARY_SERVICE}" -w "${KEYCHAIN}")" "not-a-secret" "the canary holds the non-secret value"
}

main "$@"
