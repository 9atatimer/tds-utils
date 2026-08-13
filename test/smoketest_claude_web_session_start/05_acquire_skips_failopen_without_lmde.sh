#!/usr/bin/env bash
# Given NO lmde anywhere (neither checkout-relative bin/lmde nor on PATH) but
# clai present, When session-start.sh runs, Then it notes the skipped acquire
# (fail-open), STILL runs `clai provision --copy --report`, and exits 0.
# A repo without the lmde engine degrades to configure-only, never to broken.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_session || return 1
    local dir rc rec
    dir="$(scenario_dir no_lmde)"
    make_clai_stub "${dir}/bin"

    rc="$(run_session "${dir}")"
    rec="$(clai_record "${dir}/home")"

    assert_eq "${rc}" "0" "session hook must exit 0 (fail-open)" || return 1
    assert_stderr_contains "${dir}" "lmde" "stderr names the skipped acquire" || return 1
    assert_record_argv "${rec}" "provision --copy --report" \
        "clai provision still runs without lmde" || return 1
}
main "$@"
