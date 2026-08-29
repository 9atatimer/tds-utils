#!/usr/bin/env bash
# Given a --pins file pinning CI_MAGIC_VERSION=0.6.0 and an npm stub that
# serves the ci-magic package, When `lmde acquire --pins <file>` runs,
# Then rc=0, @nine-at-a-time-media/ci-magic@0.6.0 installs,
# ~/.local/bin/naatm-ci-magic symlinks to the installed shim, and the state
# stamp is recorded under the naatm-ci-magic shortname.
#
# The bin-differs-from-npm-name case again (gadmin precedent): the package is
# @nine-at-a-time-media/ci-magic but ships `naatm-ci-magic`. The row exists so
# cloud sandboxes carry the ci.magic engine for local pre-commit consumers
# (9atatimer/Skills issue #11).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc home log pins
    dir="$(scenario_dir ci_magic_pinned)"
    home="${dir}/home"
    log="${dir}/installlog"
    pins="${dir}/pins.env"
    cat > "${pins}" <<'EOF'
CLAI_VERSION="1.0.0"
AST_MCP_VERSION="0.4.0"
SKILLS_VERSION="0.0.1"
ADMIN_VERSION="0.4.0"
DESIGNOMATIC_VERSION="0.1.0"
CI_MAGIC_VERSION="0.6.0"
EOF
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}" "0.0.1" "0.4.0" "" "0.1.0" "0.6.0"

    rc="$(run_acquire "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ci-magic@0.6.0" \
        "ci-magic package installed at the pinned version" || return 1

    local cim_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/naatm-ci-magic"
    assert_symlink_to "${home}/.local/bin/naatm-ci-magic" "${cim_bin}" \
        "naatm-ci-magic resolves on ~/.local/bin" || return 1

    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/naatm-ci-magic.version")" "0.6.0" \
        "naatm-ci-magic stamp" || return 1

    assert_stderr_contains "${dir}" "naatm-ci-magic 0.6.0" \
        "stderr names the installed ci-magic version" || return 1
}
main "$@"
