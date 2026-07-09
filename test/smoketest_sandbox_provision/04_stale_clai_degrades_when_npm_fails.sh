#!/usr/bin/env bash
# Given a healthy-but-stale clai on PATH and an npm install that fails (e.g. an
# offline cached resume), When provision.sh runs, Then it DEGRADES honestly:
# provisions with the stale clai and warns that the pin bump has not taken
# effect (Goal 4 -- honest degradation, not a hard failure).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_provision || return 1
    local dir rc
    dir="$(scenario_dir degraded)"
    write_pins "${dir}" "2.0.0"
    make_clai_stub "${dir}/bin" "1.0.0" "${dir}/record"   # healthy but STALE
    make_npm_fail_stub "${dir}/bin"                        # cannot reach the pin

    rc="$(run_provision "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_provisioned "${dir}" "--copy --report" || return 1
    assert_stderr_contains "${dir}" "STALE installed clai 1.0.0" "should warn about honest degradation" || return 1
}

main "$@"
