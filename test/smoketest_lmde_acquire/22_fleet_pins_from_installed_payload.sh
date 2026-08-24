#!/usr/bin/env bash
# Given a PRIOR acquire already installed the skills payload (seeded, current
# at the stub latest), When `lmde acquire` runs with no --pins, Then skills is
# a no-op (already current) and clai STILL installs at the fleet pin.
#
# This is the snapshot-boot path every cloud session takes: the payload is
# already there from the seed, so nothing about the pins may depend on the
# skills row doing any work this run. That used to be a real hazard, because
# the pins lived INSIDE the payload and were only readable once it was
# installed. They now sit beside the acquire engine, which removes the
# coupling entirely -- this scenario guards that a seeded, no-op skills row
# still leaves the executables correctly pinned.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc home log staged
    dir="$(scenario_dir fleet_pins_seeded)"
    home="${dir}/home"
    log="${dir}/installlog"
    staged="$(stage_lmde "${dir}" 'CLAI_VERSION="1.2.3"')"
    seed_installed_data "${home}" skills "@nine-at-a-time-media/skills" "0.2.5" >/dev/null
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${log}" "0.2.5"

    rc="$(LMDE_BIN="${staged}" run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/skills@0.2.5" "skills already current -- no reinstall" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@1.2.3" "clai installed at the fleet pin beside the engine" || return 1
    assert_not_installed "${log}" "@nine-at-a-time-media/clai@9.9.9" "clai must NOT float when the fleet pins pin it" || return 1
    assert_eq "$(cat "${home}/.local/state/tds-utils/acquire/clai.version")" "1.2.3" "clai stamp at fleet pin" || return 1
}
main "$@"
