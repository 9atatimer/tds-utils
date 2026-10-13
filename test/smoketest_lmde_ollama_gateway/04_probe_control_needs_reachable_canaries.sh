#!/usr/bin/env bash
# 04_probe_control_needs_reachable_canaries.sh
# Given the canaries, When the probe runs in control mode (unconfined, as the
# launcher runs it before the confined pass), Then it passes only while both
# canaries are reachable -- so a confined pass can never be vacuous because
# a canary was missing. A missing keychain canary is named.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local args=() line out status=0
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(/bin/zsh -f "${PROBE}" control "${args[@]}" 2>&1)" || status=$?
    assert_eq "${status}" "0" "control with both canaries present; output: ${out}"
    assert_contains "${out}" "ok canary-file-readable" "file canary control"
    assert_contains "${out}" "ok keychain-cli-reachable" "keychain cli control"
    assert_contains "${out}" "ok keychain-framework-reachable" "keychain framework control"
    assert_not_contains "${out}" "not-a-secret" "control never prints the value"

    security delete-generic-password -s "${CANARY_SERVICE}" "${KEYCHAIN}" >/dev/null
    status=0
    out="$(/bin/zsh -f "${PROBE}" control "${args[@]}" 2>&1)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "control must fail without the keychain canary"
    assert_contains "${out}" "FAIL keychain-cli-reachable" "missing keychain canary named"
    assert_contains "${out}" "${CANARY_SERVICE}" "message names the canary item"

    rm -f "${CANARY_FILE}"
    status=0
    out="$(/bin/zsh -f "${PROBE}" control "${args[@]}" 2>&1)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "control must fail without the file canary"
    assert_contains "${out}" "FAIL canary-file-readable" "missing file canary named"
}

main "$@"
