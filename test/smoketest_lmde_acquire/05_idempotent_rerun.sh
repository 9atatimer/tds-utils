#!/usr/bin/env bash
# Given clai, ast-mcp, and the skills data package already installed at the
# current latest (stamps == npm-stub latest) and an npm stub that touches a
# marker if `install` is ever called, When `lmde acquire` runs again, Then
# rc=0, stderr logs the packages up-to-date, the install marker is absent
# (npm install NOT invoked), and all symlinks remain intact.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home marker clai_target astmcp_target skills_target
    dir="$(scenario_dir idempotent)"
    home="${dir}/home"
    marker="${dir}/install-called"
    clai_target="$(seed_installed "${home}" "clai" "clai" "1.2.3")"
    astmcp_target="$(seed_installed "${home}" "ast-mcp" "ast-mcp" "0.4.0")"
    skills_target="$(seed_installed_data "${home}" "skills" "@nine-at-a-time-media/skills" "0.0.1")"
    make_npm_forbidden_install_stub "${dir}/bin" "1.2.3" "0.4.0" "${marker}" "0.0.1"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_file_absent "${marker}" "npm install must NOT run when already up-to-date" || return 1
    assert_stderr_contains "${dir}" "up-to-date" "stderr logs the up-to-date skip" || return 1
    assert_symlink_to "${home}/.local/bin/clai" "${clai_target}" "clai symlink intact" || return 1
    assert_symlink_to "${home}/.local/bin/ast-mcp" "${astmcp_target}" "ast-mcp symlink intact" || return 1
    assert_symlink_to "${home}/.local/lib/node_modules/@nine-at-a-time-media/skills" "${skills_target}" \
        "skills convention symlink intact" || return 1
}
main "$@"
