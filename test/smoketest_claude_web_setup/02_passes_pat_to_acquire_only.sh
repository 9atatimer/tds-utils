#!/usr/bin/env bash
# Given GH_AI_TOOLS_PAT set in the env-setup stage, When setup.sh runs the lmde
# stub, Then GH_AI_TOOLS_PAT is visible to `lmde acquire` (recorded by the
# stub) and setup.sh itself never writes an .npmrc anywhere under $HOME.
#
# The PAT flows THROUGH setup.sh unchanged into `lmde acquire`, which owns the
# authed npmrc. setup.sh no longer writes one itself (that machinery moved).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    local dir rc rec npmrc_hits
    dir="$(scenario_dir pat)"
    mkdir -p "${dir}/clones"
    make_checkout "${dir}/clones/tds-utils" >/dev/null

    rc="$(SETUP_SCAN_ROOTS="${dir}/clones/*" run_setup "${dir}")"
    rec="$(lmde_record "${dir}/home")"

    assert_eq "${rc}" "0" "env-setup must exit 0 (fail-open)" || return 1
    assert_file_present "${rec}" "lmde acquire was invoked" || return 1
    assert_record_pat "${rec}" "SET" \
        "GH_AI_TOOLS_PAT reaches lmde acquire" || return 1

    # setup.sh must not have written any .npmrc under the fake HOME.
    npmrc_hits="$(find "${dir}/home" -name '.npmrc' 2>/dev/null | wc -l | tr -d ' ')"
    assert_eq "${npmrc_hits}" "0" \
        "setup.sh writes no .npmrc (acquisition owns the token npmrc)" || return 1
}

main "$@"
