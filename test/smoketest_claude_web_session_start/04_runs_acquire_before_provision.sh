#!/usr/bin/env bash
# Given lmde (checkout-relative bin/lmde) and clai stubs recording into one
# shared file, When session-start.sh runs, Then it invokes `lmde acquire ...`
# BEFORE `clai provision --copy --report` -- the SessionStart hook is the
# per-session provisioning AUTHORITY (SANDBOX-LIFECYCLE.DESIGN.md): refresh
# the packages first, then configure from them.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_session || return 1
    local dir rc rec first second
    dir="$(scenario_dir acquire_first)"
    make_clai_stub "${dir}/bin"
    make_lmde_stub "${dir}/bin"

    rc="$(run_session "${dir}")"
    rec="$(clai_record "${dir}/home")"

    assert_eq "${rc}" "0" "session hook must exit 0 (fail-open)" || return 1
    assert_file_present "${rec}" "the stubs were invoked" || return 1

    first="$(sed -n '1p' "${rec}")"
    second="$(sed -n '2p' "${rec}")"
    case "${first}" in
        "INVOKE-LMDE|argv=acquire"*) ;;
        *) echo "FAIL: first invocation must be lmde acquire, got: ${first}"; cat "${rec}"; return 1 ;;
    esac
    case "${second}" in
        "INVOKE|argv=provision --copy --report") ;;
        *) echo "FAIL: second invocation must be clai provision --copy --report, got: ${second}"; cat "${rec}"; return 1 ;;
    esac
}
main "$@"
