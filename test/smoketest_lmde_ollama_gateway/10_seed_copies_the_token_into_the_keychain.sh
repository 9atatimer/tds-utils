#!/usr/bin/env bash
# 10_seed_copies_the_token_into_the_keychain.sh
# Given a human at a terminal with an unlocked 1Password desktop session,
# When they run the seeding script with the run token's op:// reference,
# Then the token lands in the keychain item the connector reads, read with
# `op read` and written through `security -i` on stdin -- so it never
# appears on any command line -- and the script never prints it (Q9).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_op
    install_security_shim
    local out
    out="$(run_seed_tty "${FAKE_REF}")"

    assert_eq "$(keychain_token)" "${FAKE_TOKEN}" "token in the keychain; output: ${out}"
    assert_contains "$(cat "${WORK}/op.log")" "op read" "token read with op read"
    assert_contains "$(cat "${WORK}/op.log")" "${FAKE_REF}" "from the given reference"
    assert_not_contains "$(cat "${WORK}/security.argv")" "${FAKE_TOKEN}" "token never on security's argv"
    assert_not_contains "${out}" "${FAKE_TOKEN}" "token never printed"
    assert_contains "${out}" "launchctl" "prints the connector's next step"
}

main "$@"
