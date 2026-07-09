#!/usr/bin/env bash
# Given an existing but INVALID ~/.claude.json, When setup.sh runs, Then it
# refuses to clobber it (contents unchanged), logs why, and still exits 0
# (fail-open -- never destroy a user's config on a parse error).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    require_python3 || return 0
    local dir rc cfg before after
    dir="$(scenario_dir invalid)"
    make_npm_stub "${dir}/bin"
    cfg="${dir}/home/.claude.json"
    printf '{ this is not json ]' > "${cfg}"
    before="$(cat "${cfg}")"

    rc="$(run_setup "${dir}")"
    after="$(cat "${cfg}")"

    assert_eq "${rc}" "0" "must exit 0 even when the config is unparseable" || return 1
    assert_eq "${after}" "${before}" "invalid ~/.claude.json must be left untouched" || return 1
    assert_stderr_contains "${dir}" "not valid JSON" "should log the refusal" || return 1
}

main "$@"
