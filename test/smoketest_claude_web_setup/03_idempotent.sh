#!/usr/bin/env bash
# Given setup.sh has already run once, When it runs again, Then ~/.claude.json is
# byte-identical (idempotent registration -- safe to run every environment boot).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    require_python3 || return 0
    local dir cfg first second
    dir="$(scenario_dir idempotent)"
    make_npm_stub "${dir}/bin"
    write_claude_fixture "${dir}/home"
    cfg="${dir}/home/.claude.json"

    run_setup "${dir}" >/dev/null
    first="$(cat "${cfg}")"
    run_setup "${dir}" >/dev/null
    second="$(cat "${cfg}")"

    assert_eq "${second}" "${first}" "second run must leave ~/.claude.json unchanged" || return 1
}

main "$@"
