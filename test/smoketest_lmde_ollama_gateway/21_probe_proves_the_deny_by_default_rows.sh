#!/usr/bin/env bash
# 21_probe_proves_the_deny_by_default_rows.sh
# Given the gateway's sandbox profile and its conformance spec, When the
# G4 probe runs confined, Then every row the spec adds for deny-by-default
# is observed as a sandbox denial: writes under /private/tmp and the
# Homebrew prefix, a listing of the user's TMPDIR, launchd and
# LaunchServices, a connect to the route's port and to a non-loopback
# address -- while the gateway home stays writable (Issue#460).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local args=() line out status=0
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(sandboxed /bin/zsh -f "${PROBE}" confined "${args[@]}" 2>&1)" || status=$?

    assert_eq "${status}" "0" "confined probe exit status; output:
${out}"
    assert_contains "${out}" "ok tmp-write-denied" "writes under /private/tmp"
    assert_contains "${out}" "ok homebrew-write-denied" "writes under the Homebrew prefix"
    assert_contains "${out}" "ok user-tmpdir-unreadable" "the user's TMPDIR tree"
    assert_contains "${out}" "ok launchd-unreachable" "launchd"
    assert_contains "${out}" "ok launchservices-unreachable" "LaunchServices"
    assert_contains "${out}" "ok loopback-route-denied" "no outbound to the route's port"
    assert_contains "${out}" "ok outbound-denied" "no outbound off the host"
    assert_contains "${out}" "ok gateway-home-writable" "the gateway home stays writable"
    assert_contains "${out}" "ok canary-file-unreadable" "the earlier rows still hold"
    assert_contains "${out}" "ok keychain-framework-denied" "the earlier rows still hold"
    [[ -z "$(find /private/tmp -maxdepth 1 -name '.ollama-gateway-probe.*' -user "$(id -un)" -print 2>/dev/null)" ]] \
        || fail "probe left a write-test file under /private/tmp"
}

main "$@"
