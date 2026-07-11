#!/usr/bin/env bash
# Given a sibling provision.sh that writes a marker if run, When
# session-start.sh runs with clai present, Then the marker is NEVER written --
# the provision.sh delegation is removed (Phase C).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_session || return 1
    local dir rc marker rec
    dir="$(scenario_dir noprovsh)"
    make_clai_stub "${dir}/bin"

    rc="$(run_session "${dir}")"
    marker="$(provision_marker "${dir}")"
    rec="$(clai_record "${dir}/home")"

    assert_eq "${rc}" "0" "session hook must exit 0 (fail-open)" || return 1
    assert_file_present "${rec}" "clai provision still runs" || return 1
    assert_file_absent "${marker}" \
        "session-start.sh never delegates to sandbox/provision.sh" || return 1
}

main "$@"
