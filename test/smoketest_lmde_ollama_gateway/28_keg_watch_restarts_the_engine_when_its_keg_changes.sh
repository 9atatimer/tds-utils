#!/usr/bin/env bash
# 28_keg_watch_restarts_the_engine_when_its_keg_changes.sh
# Given a running engine recorded against one keg, When the keg watcher
# fires and ollama on PATH now resolves to another keg (a Homebrew
# upgrade), Then it restarts the engine with `launchctl kickstart -k`, so
# the launcher re-grants the new keg and re-runs the probe (Issue#709).
# It restarts nothing When the keg is unchanged, When no engine keg is
# recorded, When ollama is not on PATH (mid-upgrade, between unlink and
# link), When the engine agent is not loaded, or When it is loaded but not
# running (an operator's clean stop stays down; launchd starts a crashed one
# through the launcher, which grants the current keg anyway); and it always
# exits 0, a failed kickstart included, since launchd would otherwise log a
# watcher failure.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

KEG_WATCH=""
DOMAIN="gui/$(id -u)"

# run_keg_watch [<path>] -- the watcher as launchd runs it, with the given
# PATH (default: the fake keg first).
run_keg_watch() {
    local path="${1:-${FAKE_KEG}/bin:${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin}"
    env -i HOME="${FAKE_HOME}" PATH="${path}" /bin/zsh -f "${KEG_WATCH}" 2>&1
}

kickstarts() {
    [[ -f "${WORK}/launchctl.log" ]] || { echo 0; return 0; }
    grep -c "kickstart -k ${DOMAIN}/${OLLAMA_LABEL}" "${WORK}/launchctl.log" 2>/dev/null || true
}

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    install_fake_launchctl
    KEG_WATCH="${TREE}/libexec/keg-watch.zsh"
    [[ -f "${KEG_WATCH}" ]] || fail "no keg watcher in the installed tree: ${KEG_WATCH}"
    local out status record="${TREE}/run/engine.keg"
    mkdir -p "${TREE}/run"
    echo "state = running" > "${WORK}/launchd/${OLLAMA_LABEL}"

    # No record: the engine never started, nothing to restart.
    status=0; out="$(run_keg_watch)" || status=$?
    assert_eq "${status}" "0" "no record; output: ${out}"
    assert_eq "$(kickstarts)" "0" "no record must not restart the engine"

    # Unchanged keg: the accept case.
    echo "${FAKE_KEG}" > "${record}"
    status=0; out="$(run_keg_watch)" || status=$?
    assert_eq "${status}" "0" "unchanged keg; output: ${out}"
    assert_eq "$(kickstarts)" "0" "an unchanged keg must not restart the engine"

    # ollama missing from PATH mid-upgrade.
    echo "${WORK}/old-keg" > "${record}"
    status=0; out="$(run_keg_watch "${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin")" || status=$?
    assert_eq "${status}" "0" "ollama not on PATH; output: ${out}"
    assert_eq "$(kickstarts)" "0" "no ollama on PATH must not restart the engine"

    # Engine agent not loaded.
    rm -f "${WORK}/launchd/${OLLAMA_LABEL}"
    status=0; out="$(run_keg_watch)" || status=$?
    assert_eq "${status}" "0" "engine not loaded; output: ${out}"
    assert_eq "$(kickstarts)" "0" "an unloaded engine must not be started by the watcher"

    # Engine agent loaded but not running: an operator's stop stays down.
    echo "state = not running" > "${WORK}/launchd/${OLLAMA_LABEL}"
    status=0; out="$(run_keg_watch)" || status=$?
    assert_eq "${status}" "0" "engine stopped; output: ${out}"
    assert_eq "$(kickstarts)" "0" "a stopped engine must not be started by the watcher"

    # The keg changed under a running engine: restart it, once.
    echo "state = running" > "${WORK}/launchd/${OLLAMA_LABEL}"
    status=0; out="$(run_keg_watch)" || status=$?
    assert_eq "${status}" "0" "changed keg; output: ${out}"
    assert_eq "$(kickstarts)" "1" "a changed keg must restart the engine"
    assert_contains "${out}" "${WORK}/old-keg" "the log names the old keg"
    assert_contains "${out}" "${FAKE_KEG}" "the log names the new keg"

    # A failed kickstart is logged, and the watcher still exits 0.
    touch "${WORK}/launchd/kickstart-fails"
    status=0; out="$(run_keg_watch)" || status=$?
    assert_eq "${status}" "0" "failed kickstart; output: ${out}"
    assert_contains "${out}" "kickstart failed" "a failed kickstart is logged"
}

main "$@"
