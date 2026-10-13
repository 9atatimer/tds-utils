#!/usr/bin/env bash
# 09_connector_keeps_the_token_off_argv_and_pins_http2.sh
# Given the run token in the keychain, When the connector launcher starts,
# Then cloudflared runs the tunnel with the transport pinned to http2,
# autoupdate off, info logging (debug would log request headers), an
# explicit config isolated from ~/.cloudflared, and the token read from a
# pipe: never in argv, never in the environment, never in a file on disk.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    connector_tree
    install_fake_cloudflared
    seed_fake_token
    local out status=0 rec argv path
    out="$(run_connector)" || status=$?
    assert_eq "${status}" "0" "launcher exit; output: ${out}"
    [[ -f "${WORK}/fake-cloudflared.out" ]] || fail "cloudflared never started; output: ${out}"
    rec="$(cat "${WORK}/fake-cloudflared.out")"
    argv="$(printf '%s\n' "${rec}" | sed -n 's/^argv //p' | tr '\n' ' ')"

    assert_contains "${argv}" "tunnel " "runs a tunnel"
    assert_contains "${argv}" "--protocol http2 " "transport pinned to http2"
    assert_contains "${argv}" "--no-autoupdate " "autoupdate off (Homebrew owns upgrades)"
    assert_contains "${argv}" "--loglevel info " "info logging, never debug"
    assert_contains "${argv}" "--config ${TREE}/connector/config.yml " "explicit config"
    assert_contains "${argv}" "run " "run subcommand"
    assert_not_contains "${argv}" "${FAKE_TOKEN}" "token not in argv"
    assert_not_contains "${argv}" "--token " "no --token flag"
    assert_contains "${rec}" "token-file-content ${FAKE_TOKEN}" "token delivered through --token-file"
    path="$(printf '%s\n' "${rec}" | sed -n 's/^token-file-path //p')"
    [[ "${path}" == /dev/fd/* ]] || fail "token file must be a pipe (/dev/fd/N), got: ${path}"
    assert_not_contains "$(printf '%s\n' "${rec}" | grep '^env ')" "${FAKE_TOKEN}" "token not in the environment"
    assert_not_contains "${rec}" "env TUNNEL_TOKEN" "no TUNNEL_TOKEN"
    assert_contains "${rec}" "env HOME=${TREE}/connector" "HOME isolated from ~/.cloudflared"
    assert_not_contains "${out}" "${FAKE_TOKEN}" "launcher never prints the token"
}

main "$@"
