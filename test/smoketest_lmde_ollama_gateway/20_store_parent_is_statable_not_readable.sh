#!/usr/bin/env bash
# 20_store_parent_is_statable_not_readable.sh
# Given the gateway's sandbox profile, When a confined process resolves the
# model store's path, Then it can stat the store's parent directory (ollama
# 0.40.3 lstats each path component and rejects every manifest otherwise,
# tds-utils Issue#443), while that directory's listing and its other files
# (ollama's identity key, history) stay unreadable (G4).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local parent status=0
    parent="$(dirname "${STORE}")"
    echo "fake identity key" > "${parent}/id_ed25519"
    echo "fake history" > "${parent}/history"

    sandboxed /usr/bin/stat -f '%HT' "${parent}" >/dev/null 2>&1 || status=$?
    assert_eq "${status}" "0" "stat of the store's parent under the profile"

    status=0
    sandboxed /bin/cat "${parent}/id_ed25519" >/dev/null 2>&1 || status=$?
    assert_ne "${status}" "0" "identity key next to the store stays unreadable"

    status=0
    sandboxed /bin/cat "${parent}/history" >/dev/null 2>&1 || status=$?
    assert_ne "${status}" "0" "history next to the store stays unreadable"

    status=0
    sandboxed /bin/ls "${parent}" >/dev/null 2>&1 || status=$?
    assert_ne "${status}" "0" "the store's parent cannot be listed"

    status=0
    sandboxed /bin/cat "${STORE}/manifests/m" >/dev/null 2>&1 || status=$?
    assert_eq "${status}" "0" "the store itself stays readable"
}

main "$@"
