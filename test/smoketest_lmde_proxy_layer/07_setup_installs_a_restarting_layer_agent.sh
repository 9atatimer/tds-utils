#!/usr/bin/env bash
# 07_setup_installs_a_restarting_layer_agent.sh
# Given a fake home, When the layer's setup.sh installs it, Then the layer's
# config and launcher land under ~/.local/share/lmde-proxy, its LaunchAgent
# is well-formed, starts at login, restarts after an unsuccessful exit
# (throttled), logs under ~/Library/Logs/lmde-proxy and runs the installed
# launcher, and it is loaded; uninstall unloads and removes it but leaves
# tenants' routes for their own uninstall. Runs without HAProxy: launchd is
# a fake here.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

LABEL="com.tds.lmde.proxy-layer"

main() {
    [[ "$(uname -s)" == "Darwin" ]] || { echo "skip: not macOS"; exit 0; }
    local work home bin p out uid
    work="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/proxy-setup.XXXXXX")" && pwd -P)"
    ROOT="${work}"
    trap fixture_cleanup EXIT INT TERM HUP
    home="${work}/home"
    bin="${work}/bin"
    uid="$(id -u)"
    mkdir -p "${home}/.local/share/lmde-proxy/routes" "${bin}" "${work}/launchd"
    echo "# a tenant route" > "${home}/.local/share/lmde-proxy/routes/tenant.cfg"
    cat > "${bin}/launchctl" <<FAKE
#!/bin/sh
echo "launchctl \$*" >> "${work}/launchctl.log"
case "\$1" in
    print) [ -e "${work}/launchd/\$(basename "\$2")" ] ;;
    bootstrap) touch "${work}/launchd/${LABEL}" ;;
    bootout) rm -f "${work}/launchd/\$(basename "\$2")" ;;
    *) exit 0 ;;
esac
FAKE
    chmod +x "${bin}/launchctl"

    out="$(env -i HOME="${home}" PATH="${bin}:/usr/bin:/bin:/usr/sbin:/sbin" "${PROXY_DIR}/setup.sh" 2>&1)" \
        || fail "install failed: ${out}"
    p="${home}/Library/LaunchAgents/${LABEL}.plist"
    [[ -f "${home}/.local/share/lmde-proxy/haproxy.cfg" ]] || fail "haproxy.cfg not installed"
    [[ -x "${home}/.local/share/lmde-proxy/libexec/launch-proxy.zsh" ]] || fail "launcher not installed"
    plutil -lint "${p}" >/dev/null || fail "plutil -lint"
    assert_eq "$(/usr/libexec/PlistBuddy -c 'Print :Label' "${p}")" "${LABEL}" "Label"
    assert_eq "$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:2' "${p}")" \
        "${home}/.local/share/lmde-proxy/libexec/launch-proxy.zsh" "runs the installed launcher"
    assert_eq "$(/usr/libexec/PlistBuddy -c 'Print :RunAtLoad' "${p}")" "true" "starts at login"
    assert_eq "$(/usr/libexec/PlistBuddy -c 'Print :KeepAlive:SuccessfulExit' "${p}")" "false" "restarts on failure"
    [[ "$(/usr/libexec/PlistBuddy -c 'Print :ThrottleInterval' "${p}")" -ge 10 ]] || fail "ThrottleInterval below 10"
    assert_eq "$(/usr/libexec/PlistBuddy -c 'Print :StandardErrorPath' "${p}")" \
        "${home}/Library/Logs/lmde-proxy/haproxy.log" "log path"
    assert_contains "$(cat "${work}/launchctl.log")" "bootstrap gui/${uid} ${p}" "layer loaded"

    out="$(env -i HOME="${home}" PATH="${bin}:/usr/bin:/bin:/usr/sbin:/sbin" "${PROXY_DIR}/setup.sh" uninstall 2>&1)" \
        || fail "uninstall failed: ${out}"
    assert_contains "$(cat "${work}/launchctl.log")" "bootout gui/${uid}/${LABEL}" "layer unloaded"
    [[ ! -e "${p}" ]] || fail "LaunchAgent left behind"
    [[ ! -e "${home}/.local/share/lmde-proxy/haproxy.cfg" ]] || fail "layer config left behind"
    [[ -f "${home}/.local/share/lmde-proxy/routes/tenant.cfg" ]] || fail "a tenant's route was removed"
}

main "$@"
