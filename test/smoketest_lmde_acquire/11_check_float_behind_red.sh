#!/usr/bin/env bash
# Given NO --pins file (both packages float) and a pre-seeded installed clai
# 1.0.0 (stamp + symlink) while the npm stub's clai latest is a newer 2.0.0,
# When `lmde acquire --check` runs, Then it prints a RED advisory that clai is
# floating and its installed 1.0.0 is behind latest 2.0.0, stays silent about
# ast-mcp (floating but never installed -> no stamp to compare), and exits 0.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire-smoke.XXXXXX")}"
    require_lmde || return 1
    local dir rc home log
    dir="$(scenario_dir check_red)"
    home="${dir}/home"
    log="${dir}/installlog"
    seed_installed "${home}" "clai" "clai" "1.0.0" >/dev/null
    make_npm_stub "${dir}/bin" "2.0.0" "0.4.0" "${log}"

    rc="$(run_check "${dir}")"

    assert_eq "${rc}" "0" "advisory check always exits 0" || return 1
    assert_stdout_contains "${dir}" "clai: floating, installed 1.0.0, latest 2.0.0" "red line names the stale float" || return 1
    # ast-mcp floats but was never installed: no stamp, so nothing to report.
    if grep -qF "ast-mcp" "${dir}/stdout" 2>/dev/null; then
        echo "FAIL: uninstalled floating ast-mcp must not appear in the report"
        cat "${dir}/stdout"; return 1
    fi
    assert_file_absent "${log}" "--check must never install" || return 1
}
main "$@"
