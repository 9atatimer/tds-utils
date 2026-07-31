#!/usr/bin/env bash
# Given a REAL directory (not a symlink) already sitting at the skills
# convention link path ~/.local/lib/node_modules/@nine-at-a-time-media/skills
# -- e.g. left by a manual `npm install -g --prefix ~/.local` -- When
# `lmde acquire` runs, Then the link step refuses instead of nesting a
# skills/skills symlink INSIDE the directory (ln -sfn treats a dir-valued
# LINK_NAME as a target directory), the pre-existing directory's content is
# left intact, a warning names the problem, and NO version stamp is written
# (so the next run retries instead of reporting current-while-stale).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log real_dir
    dir="$(scenario_dir skills_realdir)"
    home="${dir}/home"
    log="${dir}/installlog"
    real_dir="${home}/.local/lib/node_modules/@nine-at-a-time-media/skills"
    mkdir -p "${real_dir}"
    printf 'preexisting\n' > "${real_dir}/marker.txt"
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" "0.2.5"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_file_absent "${real_dir}/skills" "no nested symlink inside the real dir" || return 1
    assert_eq "$(cat "${real_dir}/marker.txt")" "preexisting" "pre-existing dir content intact" || return 1
    if [[ -L "${real_dir}" ]]; then
        echo "FAIL: acquire must not replace a real directory it does not own"
        return 1
    fi
    assert_file_absent "${home}/.local/state/tds-utils/acquire/skills.version" \
        "no stamp when the convention link could not be created" || return 1
    assert_stderr_contains "${dir}" "could not create symlink" "warning names the link failure" || return 1
}
main "$@"
