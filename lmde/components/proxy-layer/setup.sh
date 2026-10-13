#!/bin/zsh -f
# setup.sh -- install or uninstall the LMDE proxy layer
# (`lmde install proxy-layer`; lmde/components/proxy-layer/README.md).
#
# Usage: setup.sh [install|uninstall]     (default: install)
#
# install (idempotent): copies haproxy.cfg and libexec/ into
# ~/.local/share/lmde-proxy, renders the LaunchAgent
# (com.tds.lmde.proxy-layer) with absolute paths into ~/Library/LaunchAgents
# and (re)loads it. Tenants install their own routes into
# ~/.local/share/lmde-proxy/routes (e.g. lmde install ollama-gateway).
#
# uninstall: unloads and removes the layer; routes stay for their tenants'
# own uninstall.

set -euo pipefail

# --- Constants ---

readonly COMPONENT_DIR="${0:A:h}"
readonly LABEL="com.tds.lmde.proxy-layer"

typeset ROOT="" LOGDIR="" AGENTS="" DOMAIN=""

load_config() {
    [[ "$(uname -s)" == "Darwin" ]] || { print -r -- "proxy-layer: macOS only; nothing to do"; exit 0; }
    ROOT="${HOME}/.local/share/lmde-proxy"
    LOGDIR="${HOME}/Library/Logs/lmde-proxy"
    AGENTS="${HOME}/Library/LaunchAgents"
    DOMAIN="gui/$(id -u)"
}

log() { print -r -- "proxy-layer: $*"; }
die() { print -u2 -r -- "proxy-layer: $*"; exit 1; }

# --- Predicates ---

is_loaded() { launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; }

# --- Effectful helpers ---

# unload -- boot the job out and wait (bounded) until launchd lets go.
unload() {
    integer tries=0
    is_loaded || return 0
    launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
    while is_loaded && (( tries < 50 )); do
        sleep 0.1
        tries+=1
    done
}

# --- Flows ---

do_install() {
    whence -p haproxy >/dev/null || log "warning: haproxy is not on PATH; brew install haproxy (the agent will refuse to start until it is)"
    mkdir -p "${ROOT}/libexec" "${ROOT}/routes" "${LOGDIR}" "${AGENTS}"
    mkdir -p -m 700 "${ROOT}/run"
    cp "${COMPONENT_DIR}/haproxy.cfg" "${ROOT}/haproxy.cfg"
    cp "${COMPONENT_DIR}/libexec/launch-proxy.zsh" "${ROOT}/libexec/launch-proxy.zsh"
    chmod 755 "${ROOT}/libexec/launch-proxy.zsh"
    sed -e "s|@ROOT@|${ROOT}|g" -e "s|@LOGDIR@|${LOGDIR}|g" \
        "${COMPONENT_DIR}/launchd/${LABEL}.plist.in" > "${AGENTS}/${LABEL}.plist"
    plutil -lint "${AGENTS}/${LABEL}.plist" >/dev/null || die "rendered plist is invalid"
    unload
    launchctl bootstrap "${DOMAIN}" "${AGENTS}/${LABEL}.plist"
    log "installed ${ROOT} and loaded ${LABEL}"
}

do_uninstall() {
    unload
    rm -f "${AGENTS}/${LABEL}.plist" "${ROOT}/haproxy.cfg"
    rm -rf "${ROOT}/libexec" "${ROOT}/run"
    log "uninstalled ${LABEL}; tenant routes left in ${ROOT}/routes"
}

main() {
    load_config
    case "${1:-install}" in
        install) do_install ;;
        uninstall) do_uninstall ;;
        *) die "usage: setup.sh [install|uninstall]" ;;
    esac
}

main "$@"
