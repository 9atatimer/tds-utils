#!/usr/bin/env bash
# Given a PRIOR acquire already installed the skills payload (seeded, current
# at the stub latest) whose package dir carries fleet pins
# (CLAI_VERSION="1.2.3"), When `lmde acquire` runs with no --pins, Then skills
# is a no-op (already current) and clai STILL installs at the fleet pin --
# i.e. the pins are read from the convention path
# ~/.local/lib/node_modules/@nine-at-a-time-media/skills/pins.env, not only
# from a fresh install. This is the snapshot-boot path every cloud session
# takes (SANDBOX-LIFECYCLE.DESIGN.md, seed-vs-authority).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log pkg_dir
    dir="$(scenario_dir fleet_pins_seeded)"
    home="${dir}/home"
    log="${dir}/installlog"
    pkg_dir="$(seed_installed_data "${home}" skills "@nine-at-a-time-media/skills" "0.2.5")"
    cat > "${pkg_dir}/pins.env" <<'EOF'
CLAI_VERSION="1.2.3"
EOF
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${log}" "0.2.5"

    rc="$(run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/skills@0.2.5" "skills already current -- no reinstall" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@1.2.3" "clai installed at the fleet pin from the SEEDED payload" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/clai@9.9.9" "clai must NOT float when the seeded fleet pins pin it" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/clai.version")" "1.2.3" "clai stamp at fleet pin" || return 1
}
main "$@"
