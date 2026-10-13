#!/usr/bin/env bash
# 13_launchagents_restart_and_keep_secrets_out.sh
# Given a fresh install with no run token seeded, Then both LaunchAgents
# are well-formed, start at login, restart after a crash or a refused start
# (KeepAlive on unsuccessful exit, throttled), log under
# ~/Library/Logs/ollama-gateway, run the installed launchers, and carry no
# token; the external ollama is loaded, while the connector is installed
# but disabled -- it has no token, so loading it would only crash-loop.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_launchctl
    local out agents="${FAKE_HOME}/Library/LaunchAgents" p label script log
    out="$(run_setup)" || fail "install failed: ${out}"

    for label in "${OLLAMA_LABEL}" "${CONNECTOR_LABEL}"; do
        p="${agents}/${label}.plist"
        case "${label}" in
            *ollama) script="launch-ollama.zsh"; log="ollama.log" ;;
            *) script="launch-connector.zsh"; log="connector.log" ;;
        esac
        plutil -lint "${p}" >/dev/null || fail "${label}: plutil -lint"
        assert_eq "$(plist_value "${p}" Label)" "${label}" "${label}: Label"
        assert_eq "$(plist_value "${p}" ProgramArguments:2)" "${TREE}/libexec/${script}" "${label}: runs the installed launcher"
        assert_eq "$(plist_value "${p}" RunAtLoad)" "true" "${label}: starts at login"
        assert_eq "$(plist_value "${p}" KeepAlive:SuccessfulExit)" "false" "${label}: restarts after an unsuccessful exit"
        [[ "$(plist_value "${p}" ThrottleInterval)" -ge 10 ]] || fail "${label}: ThrottleInterval below 10"
        assert_eq "$(plist_value "${p}" StandardErrorPath)" "${FAKE_HOME}/Library/Logs/ollama-gateway/${log}" "${label}: log path"
        assert_not_contains "$(cat "${p}")" "--token" "${label}: no token flag"
        assert_not_contains "$(cat "${p}")" "TUNNEL_TOKEN" "${label}: no token env"
    done

    local lc
    lc="$(cat "${WORK}/launchctl.log")"
    assert_contains "${lc}" "bootstrap gui/$(id -u) ${agents}/${OLLAMA_LABEL}.plist" "external ollama loaded"
    assert_contains "${lc}" "disable gui/$(id -u)/${CONNECTOR_LABEL}" "connector disabled until seeded"
    assert_not_contains "${lc}" "bootstrap gui/$(id -u) ${agents}/${CONNECTOR_LABEL}.plist" "connector not loaded without a token"
    assert_contains "${out}" "seed-tunnel-token" "install tells the human how to finish the connector"
}

main "$@"
