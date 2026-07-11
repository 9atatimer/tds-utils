#!/usr/bin/env bash
# Given no clai on PATH, When session-start.sh runs, Then it logs that clai is
# not on PATH and skips, exits 0, and invokes nothing.
#
# Acquisition is the env-setup stage's job (`lmde acquire`); this hook is
# offline configure-only, so an absent clai is a fail-open skip, not a
# bootstrap.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_session || return 1
    local dir rc rec
    dir="$(scenario_dir noclai)"
    # No clai stub planted: PATH holds only /usr/bin:/bin plus the empty
    # scenario bin, so `command -v clai` fails.

    rc="$(run_session "${dir}")"
    rec="$(clai_record "${dir}/home")"

    assert_eq "${rc}" "0" "session hook must exit 0 (fail-open)" || return 1
    assert_stderr_contains "${dir}" "clai not on PATH" \
        "session-start.sh reports the absent clai" || return 1
    assert_stderr_contains "${dir}" "skipping provisioning (fail-open)" \
        "session-start.sh skips fail-open" || return 1
    assert_file_absent "${rec}" "nothing is invoked when clai is absent" || return 1
}

main "$@"
