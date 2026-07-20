#!/usr/bin/env bash
# Given a --pins file pinning clai=1.0.0 and ast-mcp=0.4.0 and an npm stub whose
# registry latests are EXACTLY those, When `lmde acquire --check --pins <file>`
# runs, Then it prints nothing (both current), installs nothing, and exits 0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc log pins
    dir="$(scenario_dir check_current)"
    log="${dir}/installlog"
    pins="${dir}/pins.env"
    cat > "${pins}" <<'EOF'
CLAI_VERSION="1.0.0"
AST_MCP_VERSION="0.4.0"
EOF
    make_npm_stub "${dir}/bin" "1.0.0" "0.4.0" "${log}"

    rc="$(run_check "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "advisory check always exits 0" || return 1
    assert_stdout_empty "${dir}" "current packages print nothing" || return 1
    assert_file_absent "${log}" "--check must never install" || return 1
}
main "$@"
