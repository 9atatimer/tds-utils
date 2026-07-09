#!/usr/bin/env bash
# Given a clai on PATH whose version MATCHES the pin, When provision.sh runs,
# Then it hands off to `clai provision --copy --report` immediately and never invokes npm
# (the warm-resume fast path -- no re-install when already current).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_provision || return 1
    local dir rc
    dir="$(scenario_dir fast_path)"
    write_pins "${dir}" "1.2.3"
    make_clai_stub "${dir}/bin" "1.2.3" "${dir}/record"
    make_npm_forbidden_stub "${dir}/bin" "${dir}/npm-called"

    rc="$(run_provision "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_provisioned "${dir}" "--copy --report" || return 1
    assert_file_absent "${dir}/npm-called" "npm must NOT be invoked on the version-match fast path" || return 1
}

main "$@"
