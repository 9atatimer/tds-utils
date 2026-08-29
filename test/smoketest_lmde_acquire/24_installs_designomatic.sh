#!/usr/bin/env bash
# Given a --pins file pinning DESIGNOMATIC_VERSION=0.1.0 and an npm stub that
# serves the designomatic package, When `lmde acquire --pins <file>` runs,
# Then rc=0, @nine-at-a-time-media/designomatic@0.1.0 installs,
# ~/.local/bin/designomatic symlinks to the installed shim, and the state
# stamp is recorded under the designomatic shortname.
#
# This is the skill-reachability case: the designomatic skill tells agents to
# run `designomatic`, so a sandbox that has run acquire must resolve it on
# PATH -- the gap that shipped the row in the first place was exactly a
# provisioned skill pointing at a binary nothing installed.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc home log pins
    dir="$(scenario_dir designomatic_pinned)"
    home="${dir}/home"
    log="${dir}/installlog"
    pins="${dir}/pins.env"
    cat > "${pins}" <<'EOF'
CLAI_VERSION="1.0.0"
AST_MCP_VERSION="0.4.0"
SKILLS_VERSION="0.0.1"
ADMIN_VERSION="0.4.0"
DESIGNOMATIC_VERSION="0.1.0"
EOF
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" "0.0.1" "0.4.0" "" "0.1.0"

    rc="$(run_acquire "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/designomatic@0.1.0" \
        "designomatic package installed at the pinned version" || return 1

    local dom_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/designomatic"
    assert_symlink_to "${home}/.local/bin/designomatic" "${dom_bin}" \
        "designomatic resolves on ~/.local/bin" || return 1

    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/designomatic.version")" "0.1.0" \
        "designomatic stamp" || return 1

    assert_stderr_contains "${dir}" "designomatic 0.1.0" \
        "stderr names the installed designomatic version" || return 1
}
main "$@"
