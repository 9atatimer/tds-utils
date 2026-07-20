#!/usr/bin/env bash
# Given an npm stub where `view` fails (unreachable registry / bad token), When
# `lmde acquire --check` runs, Then it prints no drift advisory on stdout, warns
# per package on stderr that the registry is unreachable, and exits 0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc
    dir="$(scenario_dir check_unreachable)"
    make_npm_fail_stub "${dir}/bin"

    rc="$(run_check "${dir}")"

    assert_eq "${rc}" "0" "advisory check always exits 0 when the registry is down" || return 1
    assert_stdout_empty "${dir}" "no drift advisory when latest cannot be resolved" || return 1
    assert_stderr_contains "${dir}" "registry unreachable" "stderr warns the registry is unreachable" || return 1
    assert_stderr_contains "${dir}" "clai" "stderr names clai" || return 1
    assert_stderr_contains "${dir}" "ast-mcp" "stderr names ast-mcp" || return 1
}
main "$@"
