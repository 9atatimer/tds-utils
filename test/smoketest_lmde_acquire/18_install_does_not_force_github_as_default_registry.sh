#!/usr/bin/env bash
# Given an npm stub that fails any install invoked with
# --registry=https://npm.pkg.github.com (the way real npm fails while resolving
# an UNSCOPED dependency against GitHub Packages, which serves only scoped
# packages), When `lmde acquire --pins <file>` runs, Then rc=0, the admin
# package still installs, ~/.local/bin/gadmin is linked, and the ephemeral
# npmrc carries the @nine-at-a-time-media scope mapping that must carry the
# private-package routing instead of a forced default registry.
#
# @nine-at-a-time-media/admin is the first package on the rail to declare an
# unscoped runtime dependency (`octokit`), so it is the first to be broken by a
# forced default registry. The other rows resolve with no dependencies at all,
# which is why the flag was harmless until now.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc home log npmrclog pins
    dir="$(scenario_dir registry_default)"
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

    rc="$(run_acquire "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/admin@0.4.0" \
        "admin installs without a forced default registry" || return 1

    local gadmin_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/gadmin"
    assert_symlink_to "${home}/.local/bin/gadmin" "${gadmin_bin}" \
        "gadmin resolves on ~/.local/bin" || return 1

    # The scope mapping is what routes the private package once the default
    # registry is left alone -- assert it is actually in the npmrc npm was
    # handed, not merely assumed.
    if ! grep -qF "@nine-at-a-time-media:registry=https://npm.pkg.github.com" \
        "${npmrclog}" 2>/dev/null; then
        echo "FAIL: npmrc handed to npm lacks the @nine-at-a-time-media scope mapping"
        echo "--- npmrc seen ---"; cat "${npmrclog}" 2>/dev/null
        return 1
    fi
}
main "$@"
