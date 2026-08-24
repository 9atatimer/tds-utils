#!/usr/bin/env bash
# Given NO --pins argument and an lmde whose engine has a SIBLING pins.env
# (CLAI_VERSION="1.2.3"; no AST_MCP_VERSION key), When `lmde acquire` runs,
# Then clai installs at the FLEET-pinned 1.2.3 (not the stub's 9.9.9 latest)
# and ast-mcp floats to latest (an absent key floats, same as with an explicit
# pins file).
#
# The pins used to ride inside the acquired skills payload, which coupled
# executable version policy to the skills SOURCE -- so moving skills to their
# own repository would have taken clai's pins with them. They now sit beside
# the acquire engine, in the repo that ships it. Resolution order is unchanged:
# explicit --pins > this sibling > float.
#
# Consequence worth stating: skills no longer has to install BEFORE the
# executables for the pins to be readable. That ordering constraint is gone,
# and this scenario deliberately no longer asserts it.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc log staged
    dir="$(scenario_dir fleet_pins)"
    log="${dir}/installlog"
    staged="$(stage_lmde "${dir}" 'CLAI_VERSION="1.2.3"')"
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${log}" "0.2.5"

    rc="$(LMDE_BIN="${staged}" run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/skills@0.2.5" "skills floats to stub latest" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@1.2.3" "clai installed at the FLEET pin beside the engine" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/clai@9.9.9" "clai must NOT float when the fleet pins pin it" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ast-mcp@0.4.0" "ast-mcp floats (absent fleet key)" || return 1
}
main "$@"
