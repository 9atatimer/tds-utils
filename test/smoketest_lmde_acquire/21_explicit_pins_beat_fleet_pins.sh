#!/usr/bin/env bash
# Given an explicit --pins file (CLAI_VERSION="0.9.9") AND a skills payload
# whose fleet pins say CLAI_VERSION="1.2.3", When `lmde acquire --pins <file>`
# runs, Then clai installs at the EXPLICIT 0.9.9 -- the passed argument
# outranks the fleet pins, which stay the no-argument default only
# (SANDBOX-LIFECYCLE.DESIGN.md D1: explicit --pins > fleet pins > float).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log fleet pins
    dir="$(scenario_dir explicit_beats_fleet)"
    home="${dir}/home"
    log="${dir}/installlog"
    fleet="${dir}/fleet-pins.env"
    pins="${dir}/pins.env"
    cat > "${fleet}" <<'EOF'
CLAI_VERSION="1.2.3"
EOF
    cat > "${pins}" <<'EOF'
CLAI_VERSION="0.9.9"
EOF
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${log}" "0.2.5" "" "${fleet}"

    rc="$(run_acquire "${dir}" --pins "${pins}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@0.9.9" "clai installed at the EXPLICIT pin" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/clai@1.2.3" "fleet pin must NOT outrank the explicit --pins" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/clai@9.9.9" "clai must NOT float" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/clai.version")" "0.9.9" "clai stamp at explicit pin" || return 1
}
main "$@"
