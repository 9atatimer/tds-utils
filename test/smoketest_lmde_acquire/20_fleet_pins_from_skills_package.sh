#!/usr/bin/env bash
# Given NO --pins argument and a stub registry whose skills payload carries a
# fleet pins.env (CLAI_VERSION="1.2.3"; no AST_MCP_VERSION key), When
# `lmde acquire` runs, Then the skills package installs FIRST (floating to the
# stub latest -- skills never pins itself from the payload it is installing),
# clai installs at the FLEET-pinned 1.2.3 (not the stub's 9.9.9 latest), and
# ast-mcp floats to latest (absent key floats, same as an explicit pins file).
# SANDBOX-LIFECYCLE.DESIGN.md D1: resolution order is explicit --pins > fleet
# pins from the acquired skills package > float.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log fleet
    dir="$(scenario_dir fleet_pins)"
    home="${dir}/home"
    log="${dir}/installlog"
    fleet="${dir}/fleet-pins.env"
    cat > "${fleet}" <<'EOF'
# fleet pins shipped inside the skills payload (D1)
CLAI_VERSION="1.2.3"
EOF
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${log}" "0.2.5" "" "${fleet}"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/skills@0.2.5" "skills floats to stub latest" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@1.2.3" "clai installed at the FLEET pin from the skills payload" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/clai@9.9.9" "clai must NOT float when the fleet pins pin it" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ast-mcp@0.4.0" "ast-mcp floats (absent fleet key)" || return 1

    # skills must be installed BEFORE clai, else the fleet pins could not have
    # been read from the payload.
    local first_skills first_clai
    first_skills="$(grep -nF "skills@" "${log}" | head -n1 | cut -d: -f1)"
    first_clai="$(grep -nF "clai@" "${log}" | head -n1 | cut -d: -f1)"
    if [ -z "${first_skills}" ] || [ -z "${first_clai}" ] \
        || [ "${first_skills}" -ge "${first_clai}" ]; then
        echo "FAIL: skills must install before clai (skills line ${first_skills:-none}, clai line ${first_clai:-none})"
        cat "${log}"
        return 1
    fi

    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/clai.version")" "1.2.3" "clai stamp at fleet pin" || return 1
}
main "$@"
