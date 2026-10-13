#!/usr/bin/env bash
# 16_keychain_checker_never_asks_for_ui.sh
# Given the probe's Security framework checker (keychain-probe.py), When it
# looks up a keychain item, Then it has switched the Security framework's
# user interaction off first, so a lookup that would still need a Keychain
# dialog is refused with a status instead of prompting -- and it says so,
# read back from the framework, on every answer (tds-utils Issue#441; G7:
# no start needs a human). The canary is still found, and a missing item
# still fails. (Its lookups are attribute-only and need no dialog in the
# first place: scenario 19.)
#
# Never constructs a lookup that would prompt: the fixture's canary admits
# any application, so a broken switch cannot raise a dialog here either.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local checker="${COMPONENT_DIR}/libexec/keychain-probe.py" out status=0

    out="$(/usr/bin/python3 "${checker}" "${CANARY_SERVICE}" "${KEYCHAIN}" 2>&1)" || status=$?
    assert_eq "${status}" "0" "the canary is retrieved without UI; output: ${out}"
    assert_contains "${out}" "user interaction off" "interaction switched off before the lookup"
    assert_not_contains "${out}" "not-a-secret" "the checker never prints the value"

    status=0
    out="$(/usr/bin/python3 "${checker}" "no.such.item" "${KEYCHAIN}" 2>&1)" || status=$?
    assert_eq "${status}" "1" "a missing item is not retrieved; output: ${out}"
    assert_contains "${out}" "user interaction off" "interaction off on the failing path too"
}

main "$@"
