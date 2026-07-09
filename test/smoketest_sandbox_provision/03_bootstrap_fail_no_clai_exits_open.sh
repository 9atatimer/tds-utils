#!/usr/bin/env bash
# Given no clai on PATH and an npm install that fails (blocked registry / bad
# token), When provision.sh runs, Then it fails OPEN: exits 0, never provisions,
# and logs why (BOOTSTRAP FAILED terminal state of the design doc's State
# Machine -- a broken bootstrap must not block the session).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_provision || return 1
    local dir rc
    dir="$(scenario_dir bootstrap_fail)"
    write_pins "${dir}" "2.0.0"
    # No clai stub -> clai absent.
    make_npm_fail_stub "${dir}/bin"

    rc="$(run_provision "${dir}")"

    assert_eq "${rc}" "0" "must exit 0 (fail-open) even when bootstrap fails" || return 1
    assert_not_provisioned "${dir}" || return 1
    assert_stderr_contains "${dir}" "Provisioning unavailable this session" "should name the failure" || return 1
}

main "$@"
