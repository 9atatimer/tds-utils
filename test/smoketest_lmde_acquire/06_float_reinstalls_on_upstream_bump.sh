#!/usr/bin/env bash
# Given a --pins file whose AST_MCP_VERSION is the literal "latest" sentinel and
# whose CLAI_VERSION key is absent (UNSET) -- so BOTH float -- and an npm stub
# reporting ast-mcp latest=0.4.0 and clai latest=1.2.3, When `lmde acquire`
# runs, Then both install at the RESOLVED CONCRETE versions and the state stamps
# record 0.4.0 and 1.2.3 (never the literal "latest"); And When upstream bumps
# ast-mcp to 0.9.9 and acquire reruns, Then a floating package REINSTALLS
# ast-mcp@0.9.9 and restamps 0.9.9 -- no permanent freeze on the sentinel.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log pins
    dir="$(scenario_dir float_bump)"
    home="${dir}/home"
    log="${dir}/installlog"
    pins="${dir}/pins.env"
    cat > "${pins}" <<'EOF'
# ast-mcp floats via the literal "latest" sentinel; clai floats via UNSET (absent key)
AST_MCP_VERSION="latest"
EOF
    make_npm_stub "${dir}/bin" "1.2.3" "0.4.0" "${log}"

    rc="$(run_acquire "${dir}" --pins "${pins}")"
    assert_eq "${rc}" "0" "fail-open exit code (first run)" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ast-mcp@0.4.0" "ast-mcp 'latest' resolves to concrete 0.4.0" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@1.2.3" "clai floats via UNSET to concrete 1.2.3" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/ast-mcp@latest" "the literal 'latest' is never an install spec" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/ast-mcp.version")" "0.4.0" "stamp records the resolved concrete version, not 'latest'" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/clai.version")" "1.2.3" "clai stamp is concrete" || return 1

    # Upstream bumps ast-mcp; a floating package must pick it up on the next run.
    make_npm_stub "${dir}/bin" "1.2.3" "0.9.9" "${log}"
    rc="$(run_acquire "${dir}" --pins "${pins}")"
    assert_eq "${rc}" "0" "fail-open exit code (second run)" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/ast-mcp@0.9.9" "float reinstalls to the new upstream 0.9.9" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/ast-mcp.version")" "0.9.9" "stamp bumps to 0.9.9 after the upstream bump" || return 1
}
main "$@"
