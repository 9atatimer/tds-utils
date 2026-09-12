#!/usr/bin/env bash
# Given an npm stub whose registry latest for skills is 9.9.9, When
# `lmde acquire --latest skills` runs, Then it prints exactly "9.9.9" to
# stdout, installs nothing, and exits 0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc log
    dir="$(scenario_dir latest_resolves)"
    log="${dir}/installlog"
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" "9.9.9"

    rc="$(run_latest "${dir}" skills)"

    assert_eq "${rc}" "0" "--latest always exits 0" || return 1
    assert_eq "$(cat "${dir}/stdout")" "9.9.9" "prints the resolved latest version" || return 1
    assert_file_absent "${log}" "--latest must never install" || return 1
}
main "$@"
