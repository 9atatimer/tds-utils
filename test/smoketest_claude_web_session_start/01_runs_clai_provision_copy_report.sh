#!/usr/bin/env bash
# Given a clai stub on PATH recording its argv, When session-start.sh runs,
# Then it invokes `clai provision --copy --report` exactly once and exits 0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_session || return 1
    local dir rc rec
    dir="$(scenario_dir provision)"
    make_clai_stub "${dir}/bin"

    rc="$(run_session "${dir}")"
    rec="$(clai_record "${dir}/home")"

    assert_eq "${rc}" "0" "session hook must exit 0 (fail-open)" || return 1
    assert_file_present "${rec}" "clai was invoked" || return 1
    assert_record_argv "${rec}" "provision --copy --report" \
        "session-start.sh runs clai provision --copy --report exactly once" || return 1
}

main "$@"
