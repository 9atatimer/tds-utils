#!/usr/bin/env bash
# Given a sandbox that exports NPM_CONFIG_REGISTRY pointing at GitHub Packages
# (an ambient default that cannot serve unscoped packages), When `lmde acquire
# --pins <file>` runs, Then rc=0, the admin package still installs and
# ~/.local/bin/gadmin is linked.
#
# npm's config precedence is command-line flag > environment > npmrc > builtin
# default. Setting the public registry only in the ephemeral npmrc therefore
# sits BELOW the environment and pins nothing: an ambient NPM_CONFIG_REGISTRY
# silently wins, `octokit` 404s, and the fail-open path leaves gadmin
# unavailable. The install must assert the public default at command-line
# priority for this to hold.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc home log npmrclog pins
    dir="$(scenario_dir ambient_registry)"
    home="${dir}/home"
    log="${dir}/installlog"
    npmrclog="${dir}/npmrc-seen"
    pins="${dir}/pins.env"
    cat > "${pins}" <<'EOF'
CLAI_VERSION="1.0.0"
AST_MCP_VERSION="0.4.0"
SKILLS_VERSION="0.0.1"
ADMIN_VERSION="0.4.0"
EOF
    make_npm_registry_strict_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" \
        "${npmrclog}" "0.0.1" "0.4.0"

    rc="$(TEST_NPM_CONFIG_REGISTRY="https://npm.pkg.github.com" \
        run_acquire "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/admin@0.4.0" \
        "admin installs despite a hostile ambient NPM_CONFIG_REGISTRY" || return 1

    local gadmin_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/gadmin"
    assert_symlink_to "${home}/.local/bin/gadmin" "${gadmin_bin}" \
        "gadmin resolves on ~/.local/bin" || return 1

    # The scope mapping must survive the public default -- --registry sets only
    # the DEFAULT registry, so @nine-at-a-time-media:registry still routes the
    # private root package to GitHub Packages.
    if ! grep -qF "@nine-at-a-time-media:registry=https://npm.pkg.github.com" \
        "${npmrclog}" 2>/dev/null; then
        echo "FAIL: npmrc handed to npm lacks the @nine-at-a-time-media scope mapping"
        echo "--- npmrc seen ---"; cat "${npmrclog}" 2>/dev/null
        return 1
    fi
}
main "$@"
