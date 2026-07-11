#!/usr/bin/env bash
# Given a seeded ~/.claude.json, When setup.sh runs (registration moved to clai
# provision), Then ~/.claude.json is BYTE-FOR-BYTE unchanged (no ast-mcp
# registration, no disabledMcpServers edit).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    local dir rc cfg before
    dir="$(scenario_dir claudejson)"
    mkdir -p "${dir}/clones"
    make_checkout "${dir}/clones/tds-utils" >/dev/null
    write_claude_fixture "${dir}/home"
    cfg="${dir}/home/.claude.json"
    before="${dir}/claude.json.before"
    cp "${cfg}" "${before}"

    rc="$(SETUP_SCAN_ROOTS="${dir}/clones/*" run_setup "${dir}")"

    assert_eq "${rc}" "0" "env-setup must exit 0 (fail-open)" || return 1
    assert_files_identical "${before}" "${cfg}" \
        "setup.sh leaves ~/.claude.json byte-for-byte unchanged" || return 1
}

main "$@"
