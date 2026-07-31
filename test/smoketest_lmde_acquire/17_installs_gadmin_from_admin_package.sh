#!/usr/bin/env bash
# Given a --pins file pinning ADMIN_VERSION=0.4.0 and an npm stub that serves
# the admin package, When `lmde acquire --pins <file>` runs, Then rc=0,
# @nine-at-a-time-media/admin@0.4.0 installs, ~/.local/bin/gadmin symlinks to
# the installed shim (the bin name differs from the npm name -- `admin` ships
# `gadmin`), and the state stamp is recorded under the gadmin shortname.
#
# This is the sandbox-reachability case: a cloud sandbox that has run acquire
# must resolve `gadmin` on PATH, since the github-workflow skill ranks it ahead
# of the MCP tools and `gh` is not installed there.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc home log pins
    dir="$(scenario_dir gadmin_pinned)"
    home="${dir}/home"
    log="${dir}/installlog"
    pins="${dir}/pins.env"
    cat > "${pins}" <<'EOF'
CLAI_VERSION="1.0.0"
AST_MCP_VERSION="0.4.0"
SKILLS_VERSION="0.0.1"
ADMIN_VERSION="0.4.0"
EOF
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" "0.0.1" "0.4.0"

    rc="$(run_acquire "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/admin@0.4.0" \
        "admin package installed at the pinned version" || return 1

    local gadmin_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/gadmin"
    assert_symlink_to "${home}/.local/bin/gadmin" "${gadmin_bin}" \
        "gadmin resolves on ~/.local/bin" || return 1

    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/gadmin.version")" "0.4.0" \
        "gadmin stamp" || return 1

    assert_stderr_contains "${dir}" "gadmin 0.4.0" \
        "stderr names the installed gadmin version" || return 1
}
main "$@"
