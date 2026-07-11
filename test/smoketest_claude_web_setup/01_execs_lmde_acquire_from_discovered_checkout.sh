#!/usr/bin/env bash
# Given a checkout reachable ONLY by scanning (CLAUDE_PROJECT_DIR unset, as in
# the real Claude web setup stage) whose bin/lmde is a recording stub, When
# setup.sh runs, Then it invokes `<root>/bin/lmde acquire --pins
# <root>/sandbox/pins.env` exactly once and exits 0.
#
# This is the Phase-C contract: acquisition moved out of setup.sh into
# `lmde acquire`; setup.sh only discovers the checkout and hands off. It also
# covers the #118 discovery bug (setup.sh must NOT ask for $CLAUDE_PROJECT_DIR,
# which this stage never sets).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    local dir rc root rec
    dir="$(scenario_dir acquire)"
    mkdir -p "${dir}/clones"
    make_checkout "${dir}/clones/tds-utils" >/dev/null
    # discover_checkout prints the physical path (pwd -P); resolve the same way.
    root="$(cd "${dir}/clones/tds-utils" && pwd -P)"

    # CLAUDE_PROJECT_DIR deliberately unset; only the scan can find it.
    rc="$(SETUP_SCAN_ROOTS="${dir}/clones/*" run_setup "${dir}")"
    rec="$(lmde_record "${dir}/home")"

    assert_eq "${rc}" "0" "env-setup must exit 0 (fail-open)" || return 1
    assert_stderr_contains "${dir}" "checkout discovered at ${root}" \
        "the checkout is found by scanning, with no CLAUDE_PROJECT_DIR" || return 1
    assert_file_present "${rec}" "lmde acquire was invoked" || return 1
    assert_record_argv "${rec}" "acquire --pins ${root}/sandbox/pins.env" \
        "setup.sh execs lmde acquire with the pins file exactly once" || return 1
}

main "$@"
