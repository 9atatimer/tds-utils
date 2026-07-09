#!/usr/bin/env bash
# Given an UNSET CLAI_VERSION pin but a healthy clai already on PATH (the laptop
# pre-rollout case), When provision.sh runs, Then it uses that clai to provision
# directly and never invokes npm (the pin is only the sandbox delivery lever;
# an already-present clai needs no bootstrap).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_provision || return 1
    local dir rc
    dir="$(scenario_dir unset_healthy)"
    write_pins "${dir}" "UNSET"
    make_clai_stub "${dir}/bin" "9.9.9" "${dir}/record"
    make_npm_forbidden_stub "${dir}/bin" "${dir}/npm-called"

    rc="$(run_provision "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_provisioned "${dir}" "--copy" || return 1
    assert_file_absent "${dir}/npm-called" "must NOT invoke npm when a healthy clai is present" || return 1
}

main "$@"
