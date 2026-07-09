#!/usr/bin/env bash
# Given ~/.claude.json is a SYMLINK (or other non-regular file), When setup.sh
# runs, Then register_user_scope refuses to touch it (leaves the symlink and its
# target untouched), logs why, and the run still exits 0 (fail-open) -- a setup
# script running automatically with a token must not write through a symlink.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    require_python3 || return 0
    local dir rc cfg decoy before
    dir="$(scenario_dir symlink)"
    make_npm_stub "${dir}/bin"
    # ~/.claude.json is a symlink to a decoy regular file with known content.
    decoy="${dir}/home/decoy.json"
    cfg="${dir}/home/.claude.json"
    printf '{"unrelated":"keep me"}\n' > "${decoy}"
    ln -s "${decoy}" "${cfg}"
    before="$(cat "${decoy}")"

    rc="$(run_setup "${dir}")"

    assert_eq "${rc}" "0" "must exit 0 (fail-open) when ~/.claude.json is a symlink" || return 1
    assert_stderr_contains "${dir}" "not a regular file" "should log the refusal" || return 1
    [[ -L "${cfg}" ]] || { echo "FAIL: ~/.claude.json symlink should be left in place"; return 1; }
    assert_eq "$(cat "${decoy}")" "${before}" "symlink target must be left untouched" || return 1
    # user-scope binary still installs even though registration was refused.
    assert_file_present "${dir}/home/.local/bin/ast-mcp" "ast-mcp binary still installed" || return 1
}

main "$@"
