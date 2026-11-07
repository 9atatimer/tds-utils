#!/usr/bin/env bash
# 30_setup_installs_the_keg_watch.sh
# Given ollama on the engine's PATH, When the gateway is installed, Then a
# keg-watch LaunchAgent is loaded that runs the installed watcher whenever
# the directory holding `ollama` or the directory holding its kegs changes
# -- the two places a Homebrew upgrade relinks and cleans up -- so the
# engine is restarted onto the new keg (Issue#709). It does not run at
# load and is not kept alive: it is event-driven, never on a clock.
# When the gateway is uninstalled, Then the agent is unloaded and removed.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

WATCH_LABEL="com.tds.lmde.ollama-gateway.keg-watch"

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    install_fake_launchctl
    local out p="${FAKE_HOME}/Library/LaunchAgents/${WATCH_LABEL}.plist" watched

    out="$(env -i HOME="${FAKE_HOME}" PATH="${FAKE_KEG}/bin:${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin" \
        OLLAMA_GATEWAY_KEYCHAIN="${KEYCHAIN}" "${SETUP}" 2>&1)" || fail "install failed: ${out}"

    [[ -f "${p}" ]] || fail "no keg-watch agent installed; output: ${out}"
    plutil -lint "${p}" >/dev/null || fail "keg-watch plist: plutil -lint"
    assert_eq "$(plist_value "${p}" Label)" "${WATCH_LABEL}" "Label"
    assert_eq "$(plist_value "${p}" ProgramArguments:2)" "${TREE}/libexec/keg-watch.zsh" "runs the installed watcher"
    watched="$(plist_value "${p}" WatchPaths)"
    assert_contains "${watched}" "${FAKE_KEG}/bin" "watches the directory holding ollama"
    assert_contains "${watched}" "${WORK}"$'\n' "watches the directory holding the kegs"
    assert_ne "$(plist_value "${p}" RunAtLoad)" "true" "not run at load"
    plist_value "${p}" KeepAlive >/dev/null && fail "the watcher must not be kept alive"
    plist_value "${p}" StartInterval >/dev/null && fail "the watcher must not run on a clock"
    assert_eq "$(plist_value "${p}" StandardErrorPath)" "${FAKE_HOME}/Library/Logs/ollama-gateway/ollama.log" "logs beside the engine"
    assert_contains "$(cat "${WORK}/launchctl.log")" "bootstrap gui/$(id -u) ${p}" "keg-watch loaded"

    out="$(run_setup uninstall)" || fail "uninstall failed: ${out}"
    [[ ! -e "${p}" ]] || fail "keg-watch plist left behind"
    assert_contains "$(cat "${WORK}/launchctl.log")" "bootout gui/$(id -u)/${WATCH_LABEL}" "keg-watch unloaded"
}

main "$@"
