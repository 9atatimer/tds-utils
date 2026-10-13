#!/usr/bin/env bash
# 08_connector_refuses_without_a_token.sh
# Given no run token in the keychain (or an empty one), When the connector
# launcher starts, Then it exits non-zero with a message naming the missing
# keychain item and the seeding step, and cloudflared never starts -- so it
# can never fall back to another tunnel's credentials in ~/.cloudflared.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    connector_tree
    install_fake_cloudflared
    local out status=0

    out="$(run_connector)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "must refuse without a token; output: ${out}"
    assert_contains "${out}" "${TOKEN_SERVICE}" "names the keychain item"
    assert_contains "${out}" "seed-tunnel-token" "names the seeding step"
    [[ ! -e "${WORK}/fake-cloudflared.out" ]] || fail "cloudflared started without a token"

    seed_fake_token " "
    status=0
    out="$(run_connector)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "must refuse a blank token; output: ${out}"
    [[ ! -e "${WORK}/fake-cloudflared.out" ]] || fail "cloudflared started with a blank token"
}

main "$@"
