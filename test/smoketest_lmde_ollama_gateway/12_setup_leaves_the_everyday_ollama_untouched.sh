#!/usr/bin/env bash
# 12_setup_leaves_the_everyday_ollama_untouched.sh
# Given the everyday ollama's footprint (its LaunchAgent, ~/.ollama with its
# identity key, history, config and store), When the gateway is installed
# and then uninstalled, Then that footprint is byte-for-byte unchanged and
# launchd was never asked about the everyday ollama (G8); and uninstall
# removes everything install created (LaunchAgents, tree, canaries, route).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    rm -rf "${TREE}" "${CANARY_FILE}"
    security delete-generic-password -s "${CANARY_SERVICE}" "${KEYCHAIN}" >/dev/null 2>&1
    everyday_fixture
    install_fake_launchctl
    local before after out routes="${FAKE_HOME}/.local/share/lmde-proxy/routes"
    before="$(everyday_snapshot)"

    out="$(run_setup)" || fail "install failed: ${out}"
    [[ -f "${FAKE_HOME}/Library/LaunchAgents/${OLLAMA_LABEL}.plist" ]] || fail "ollama LaunchAgent not installed"
    [[ -f "${FAKE_HOME}/Library/LaunchAgents/${CONNECTOR_LABEL}.plist" ]] || fail "connector LaunchAgent not installed"
    [[ -x "${TREE}/libexec/launch-ollama.zsh" ]] || fail "launcher not installed into the tree"
    [[ -f "${TREE}/sandbox/ollama-gateway.sb" ]] || fail "profile not installed"
    [[ -d "${TREE}/home/.ollama" ]] || fail "gateway home not created"
    [[ -f "${CANARY_FILE}" ]] || fail "file canary not created"
    security find-generic-password -s "${CANARY_SERVICE}" "${KEYCHAIN}" >/dev/null 2>&1 || fail "keychain canary not created"
    [[ -f "${routes}/ollama-gateway.cfg" && -f "${routes}/ollama-gateway.env" && -f "${routes}/ollama-gateway.deadline.http" ]] \
        || fail "route not installed into the proxy layer"
    assert_eq "$(everyday_snapshot)" "${before}" "everyday footprint after install"

    out="$(run_setup uninstall)" || fail "uninstall failed: ${out}"
    after="$(everyday_snapshot)"
    assert_eq "${after}" "${before}" "everyday footprint after uninstall"
    assert_not_contains "$(cat "${WORK}/launchctl.log")" "sh.brew.ollama" "launchd never asked about the everyday ollama"
    [[ ! -e "${FAKE_HOME}/Library/LaunchAgents/${OLLAMA_LABEL}.plist" ]] || fail "ollama LaunchAgent left behind"
    [[ ! -e "${FAKE_HOME}/Library/LaunchAgents/${CONNECTOR_LABEL}.plist" ]] || fail "connector LaunchAgent left behind"
    [[ ! -e "${TREE}" ]] || fail "gateway tree left behind"
    [[ ! -e "${CANARY_FILE}" ]] || fail "file canary left behind"
    ! security find-generic-password -s "${CANARY_SERVICE}" "${KEYCHAIN}" >/dev/null 2>&1 || fail "keychain canary left behind"
    [[ ! -e "${routes}/ollama-gateway.cfg" ]] || fail "route left behind"
}

main "$@"
