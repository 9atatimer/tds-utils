#!/usr/bin/env bash
# Given an UNSET CLAI_VERSION pin and no clai on PATH, When provision.sh runs,
# Then it is disarmed: it never invokes npm, prints the loud fill-in warning,
# and exits 0 (provisioning disabled, session still starts).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_provision || return 1
    local dir rc
    dir="$(scenario_dir unset_no_clai)"
    write_pins "${dir}" "UNSET"
    make_npm_forbidden_stub "${dir}/bin" "${dir}/npm-called"

    rc="$(run_provision "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_not_provisioned "${dir}" || return 1
    assert_stderr_contains "${dir}" "UNSET CLAI_VERSION" "should print the disarmed warning" || return 1
    assert_file_absent "${dir}/npm-called" "must NOT invoke npm when the pin is unset" || return 1
}

main "$@"
