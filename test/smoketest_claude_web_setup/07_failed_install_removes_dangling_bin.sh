#!/usr/bin/env bash
# Given an npm that fails AFTER creating the bin symlink (a real interrupted
# `npm install -g` does exactly this), When setup.sh runs, Then no dangling
# ~/.local/bin/ast-mcp is left behind.
#
# Why this matters (#113): the committed .mcp.json spawns
# "${HOME}/.local/bin/ast-mcp". A dangling symlink there makes the MCP client
# ENOENT on every connect attempt -- strictly worse than the path not existing,
# which would at least be an honest, uniform failure. A partial install must
# leave the system exactly as clean as no install.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    local dir rc bin
    dir="$(scenario_dir dangling)"
    make_npm_dangling_stub "${dir}/bin"
    bin="${dir}/home/.local/bin/ast-mcp"

    rc="$(run_setup "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    # -e follows symlinks, so a dangling link is "absent" to assert_file_absent;
    # test the link itself with -L to prove it was really removed.
    if [[ -L "${bin}" ]]; then
        echo "FAIL: dangling symlink survived a failed install (#113): ${bin}"
        return 1
    fi
    assert_stderr_contains "${dir}" "removed dangling" "cleanup is reported, not silent" || return 1
}

main "$@"
