#!/usr/bin/env bash
# Given a bin/lmde stub that exits 1, When setup.sh runs, Then setup.sh still
# exits 0 and logs 'lmde acquire failed (non-fatal)'.
#
# `lmde acquire` is itself fail-open and normally returns 0 even when it
# degrades; a non-zero from it is an unexpected hard error that setup.sh must
# absorb rather than propagate (env-setup must never fail the build).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    local dir rc rec
    dir="$(scenario_dir acqfail)"
    mkdir -p "${dir}/clones"
    make_checkout "${dir}/clones/tds-utils" fail >/dev/null

    rc="$(SETUP_SCAN_ROOTS="${dir}/clones/*" run_setup "${dir}")"
    rec="$(lmde_record "${dir}/home")"

    assert_eq "${rc}" "0" "env-setup stays fail-open even when acquire fails" || return 1
    assert_file_present "${rec}" "lmde acquire was still invoked" || return 1
    assert_stderr_contains "${dir}" "lmde acquire failed (non-fatal)" \
        "setup.sh logs the non-fatal acquire failure" || return 1
}

main "$@"
