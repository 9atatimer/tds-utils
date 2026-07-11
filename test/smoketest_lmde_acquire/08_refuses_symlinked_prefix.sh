#!/usr/bin/env bash
# Given the install prefix (~/.local/share/tds-utils/acquire/_npm) pre-planted
# as a SYMLINK to another tree and a reachable npm stub, When `lmde acquire`
# runs, Then it REFUSES to install (npm --prefix would write through the link,
# outside the intended tree): nothing is installed, the symlink target is left
# empty, it warns "refusing to install", and it still exits 0 (fail-open).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log prefix decoy
    dir="$(scenario_dir symlinked_prefix)"
    home="${dir}/home"
    log="${dir}/installlog"
    # Plant ACQUIRE_PREFIX as a symlink pointing at a decoy tree outside it.
    prefix="${home}/.local/share/tds-utils/acquire/_npm"
    decoy="${dir}/decoy"
    mkdir -p "$(dirname "${prefix}")" "${decoy}"
    ln -s "${decoy}" "${prefix}"
    make_npm_stub "${dir}/bin" "1.2.3" "0.4.0" "${log}"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code on an unsafe prefix" || return 1
    assert_stderr_contains "${dir}" "refusing to install" "warns about the unsafe prefix" || return 1
    assert_file_absent "${log}" "no npm install ran" || return 1
    assert_file_absent "${decoy}/node_modules" "nothing written through the symlink into the decoy" || return 1
    assert_file_absent "${home}/.local/bin/clai" "clai not linked" || return 1
    assert_file_absent "${home}/.local/bin/ast-mcp" "ast-mcp not linked" || return 1
}
main "$@"
