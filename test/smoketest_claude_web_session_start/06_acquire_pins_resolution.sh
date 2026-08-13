#!/usr/bin/env bash
# Pin-source resolution in the wrapper (SANDBOX-LIFECYCLE.DESIGN.md D1):
#
# Case A: the fleet pins exist in the fake HOME (the acquired skills payload
# at ~/.local/lib/node_modules/@nine-at-a-time-media/skills/pins.env). Then
# the wrapper passes NO --pins -- the acquire engine resolves the fleet pins
# itself; a wrapper-passed file would wrongly outrank them.
#
# Case B: no fleet pins, but the checkout carries sandbox/pins.env (the
# legacy tds-utils file). Then the wrapper passes --pins <that file> as the
# transition fallback, so the first-ever acquire is still gated.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_session || return 1
    local dir rc rec line

    # --- Case A: fleet pins present -> bare `acquire` --------------------
    dir="$(scenario_dir fleet_present)"
    make_clai_stub "${dir}/bin"
    make_lmde_stub "${dir}/bin"
    mkdir -p "${dir}/home/.local/lib/node_modules/@nine-at-a-time-media/skills"
    printf 'CLAI_VERSION="1.0.0"\n' \
        > "${dir}/home/.local/lib/node_modules/@nine-at-a-time-media/skills/pins.env"
    # A checkout pins file ALSO present -- must be ignored when fleet exists.
    printf 'CLAI_VERSION="0.0.1"\n' > "${dir}/sandbox/pins.env"

    rc="$(run_session "${dir}")"
    rec="$(clai_record "${dir}/home")"
    assert_eq "${rc}" "0" "case A: exit 0" || return 1
    line="$(grep 'INVOKE-LMDE|' "${rec}" | head -n1)"
    assert_eq "${line}" "INVOKE-LMDE|argv=acquire" \
        "case A: fleet pins present -> bare acquire (engine resolves them)" || return 1

    # --- Case B: no fleet pins -> --pins <checkout sandbox/pins.env> -----
    dir="$(scenario_dir fleet_absent)"
    make_clai_stub "${dir}/bin"
    make_lmde_stub "${dir}/bin"
    printf 'CLAI_VERSION="0.0.1"\n' > "${dir}/sandbox/pins.env"

    rc="$(run_session "${dir}")"
    rec="$(clai_record "${dir}/home")"
    assert_eq "${rc}" "0" "case B: exit 0" || return 1
    line="$(grep 'INVOKE-LMDE|' "${rec}" | head -n1)"
    assert_eq "${line}" "INVOKE-LMDE|argv=acquire --pins ${dir}/sandbox/pins.env" \
        "case B: no fleet pins -> legacy checkout pins passed explicitly" || return 1
}
main "$@"
