#!/usr/bin/env bash
# 02_probe_fails_every_check_unconfined.sh
# Given no sandbox at all, When the probe runs in confined mode, Then it
# exits non-zero and names every confinement check that failed -- so a
# launcher that forgot sandbox-exec, or a profile that stopped applying,
# can never pass. (The accept case is 01.)

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local args=() line out status=0
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(/bin/zsh -f "${PROBE}" confined "${args[@]}" 2>&1)" || status=$?

    [[ "${status}" -ne 0 ]] || fail "unconfined probe must exit non-zero; output:
${out}"
    assert_contains "${out}" "FAIL canary-file-unreadable" "file canary readable unconfined"
    assert_contains "${out}" "FAIL keychain-cli-denied" "keychain cli unconfined"
    assert_contains "${out}" "FAIL keychain-framework-denied" "keychain framework unconfined"
    assert_contains "${out}" "FAIL loopback-everyday-denied" "loopback unconfined"
    assert_contains "${out}" "FAIL store-write-denied" "store write unconfined"
    assert_contains "${out}" "FAIL guard-write-denied" "guard write unconfined"
    assert_not_contains "${out}" "not-a-secret" "the probe never prints a keychain value"
    # The probe cleans up after a store write it should never have managed.
    [[ -z "$(find "${STORE}" -name '.ollama-gateway-probe.*' -print)" ]] \
        || fail "probe left a write-test file in the store"
}

main "$@"
