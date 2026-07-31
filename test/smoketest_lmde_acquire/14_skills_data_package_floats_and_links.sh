#!/usr/bin/env bash
# Given a reachable stub registry whose skills latest is 0.2.5 and NO --pins
# file, When `lmde acquire` runs, Then the @nine-at-a-time-media/skills DATA
# package floats to 0.2.5 (installed into the acquire prefix), the state stamp
# records 0.2.5, the convention symlink
# ~/.local/lib/node_modules/@nine-at-a-time-media/skills points at the
# installed package directory, and -- because a data package ships no binary --
# NO ~/.local/bin/skills link exists and no missing-binary warning is emitted.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log
    dir="$(scenario_dir skills_float)"
    home="${dir}/home"
    log="${dir}/installlog"
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" "0.2.5"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/skills@0.2.5" "skills floats to stub latest" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/skills.version")" "0.2.5" "skills stamp floated" || return 1

    local pkg_dir="${home}/.local/share/tds-utils/acquire/_npm/node_modules/@nine-at-a-time-media/skills"
    assert_file_present "${pkg_dir}/package.json" "skills package materialized in the prefix" || return 1
    assert_symlink_to "${home}/.local/lib/node_modules/@nine-at-a-time-media/skills" "${pkg_dir}" \
        "convention symlink points at the installed package dir" || return 1

    assert_file_absent "${home}/.local/bin/skills" "data package must NOT get a bin link" || return 1
    if grep -qF "skills: npm install reported success but" "${dir}/stderr" 2>/dev/null; then
        echo "FAIL: data package wrongly treated as a missing binary"
        cat "${dir}/stderr"
        return 1
    fi
}
main "$@"
