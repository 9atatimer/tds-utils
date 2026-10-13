#!/usr/bin/env bash
# 01_probe_passes_under_the_profile.sh
# Given the gateway's sandbox profile, When the G4 probe runs confined under
# it, Then every check passes: the file canary outside the allow-listed trees
# is unreadable, the keychain canary is unretrievable through
# /usr/bin/security and through the Security framework, loopback to the
# everyday ollama's port is denied, and the model store and the launcher's
# own tree are unwritable -- while the store stays readable.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local args=() line out status=0
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(sandboxed /bin/zsh -f "${PROBE}" confined "${args[@]}" 2>&1)" || status=$?

    assert_eq "${status}" "0" "confined probe exit status"
    assert_contains "${out}" "ok canary-file-unreadable" "file canary"
    assert_contains "${out}" "ok keychain-cli-denied" "keychain via /usr/bin/security"
    assert_contains "${out}" "ok keychain-framework-denied" "keychain via Security framework"
    assert_contains "${out}" "ok loopback-everyday-denied" "loopback to 11434"
    assert_contains "${out}" "ok store-write-denied" "store writes"
    assert_contains "${out}" "ok guard-write-denied" "launcher tree writes"
    assert_contains "${out}" "ok store-readable" "store reads"
    assert_not_contains "${out}" "not-a-secret" "the probe never prints a keychain value"
    assert_not_contains "${out}" "canary: not a secret" "the probe never prints the file canary"
}

main "$@"
