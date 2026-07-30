#!/usr/bin/env bash
# Given a --pins file that sets only SKILLS_VERSION="0.1.0" while the stub's
# skills latest is a DIFFERENT 9.9.9 (clai latest 1.0.0, ast-mcp latest 0.4.0),
# When `lmde acquire --pins <file>` runs, Then skills installs at exactly the
# pinned 0.1.0 (NOT the 9.9.9 latest -- the pin is honored), the other two
# packages float, rc=0, and the skills stamp records 0.1.0. Mirror of
# scenario 02 for the data package.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log pins
    dir="$(scenario_dir skills_pin)"
    home="${dir}/home"
    log="${dir}/installlog"
    pins="${dir}/pins.env"
    cat > "${pins}" <<'EOF'
# a --pins override that pins skills and floats the rest
SKILLS_VERSION="0.1.0"
EOF
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" "9.9.9"

    rc="$(run_acquire "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/skills@0.1.0" "skills installed at the pinned version" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/skills@9.9.9" "skills must NOT float to latest when pinned" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@1.0.0" "clai floats to latest" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ast-mcp@0.4.0" "ast-mcp floats to latest" || return 1

    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/skills.version")" "0.1.0" "skills stamp pinned" || return 1
}
main "$@"
