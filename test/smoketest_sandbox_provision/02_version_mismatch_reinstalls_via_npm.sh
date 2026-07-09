#!/usr/bin/env bash
# Given a clai on PATH whose version differs from the pin, When provision.sh
# runs, Then it re-installs the pinned version from GitHub Packages via npm and
# provisions with the freshly installed clai (the pin bump must take effect on
# every networked session -- the ai-tools #72 stale-binary guard).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_provision || return 1
    local dir rc
    dir="$(scenario_dir mismatch)"
    write_pins "${dir}" "2.0.0"
    make_clai_stub "${dir}/bin" "1.0.0" "${dir}/record"      # healthy but STALE
    make_npm_install_stub "${dir}/bin" "2.0.0" "${dir}/record"  # reinstall plants 2.0.0

    rc="$(run_provision "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_file_present "${dir}/prefix/node_modules/.bin/clai" "npm install should plant the pinned clai bin" || return 1
    assert_provisioned "${dir}" "--copy" || return 1
    assert_stderr_contains "${dir}" "!= pinned 2.0.0" "should log the stale-vs-pin mismatch" || return 1
    assert_stderr_contains "${dir}" "installed pinned clai 2.0.0 from GitHub Packages" "should log the successful re-install" || return 1
}

main "$@"
