#!/bin/zsh -f
# setup.sh -- install or uninstall the Ollama Gateway's laptop side
# (docs/design/OLLAMA-GATEWAY.DESIGN.md; `lmde install ollama-gateway`).
#
# Usage: setup.sh [install|uninstall]     (default: install)
#
# install (idempotent):
#   - copies the launchers, probe, the profile template and its
#     conformance table, gateway.env and the connector config into the
#     gateway tree, and renders the profile for this machine's kernel, ~/.local/share/ollama-gateway; creates
#     its home/ (the external ollama's HOME)
#   - creates the G4 probe's canaries: a file outside the tree,
#     ~/.local/state/ollama-gateway-probe/canary, and a keychain item
#     (service lmde.ollama-gateway.probe-canary) -- both hold the literal
#     "not-a-secret"
#   - installs the gateway's route into the LMDE proxy layer
#     (~/.local/share/lmde-proxy/routes) and restarts the layer if loaded
#   - renders both LaunchAgents into ~/Library/LaunchAgents, loads the
#     external ollama, and loads the connector only once a human has seeded
#     its run token (seed-tunnel-token.zsh); until then it stays disabled,
#     so it neither crash-loops now nor starts at the next login
#
# uninstall: unloads and removes all of the above. The run token in the
# keychain is the human's to delete; the command is printed.
#
# Never touches the everyday ollama (127.0.0.1:11434, its LaunchAgent, its
# config or its store) -- G8.
#
# Environment (tests only): OLLAMA_GATEWAY_KEYCHAIN, a keychain file used
# instead of the login keychain; LMDE_PROXY_ROOT, the layer's root.

set -euo pipefail
setopt null_glob

# --- Constants ---

readonly COMPONENT_DIR="${0:A:h}"
readonly OLLAMA_LABEL="com.tds.lmde.ollama-gateway.ollama"
readonly CONNECTOR_LABEL="com.tds.lmde.ollama-gateway.connector"
readonly PROXY_LABEL="com.tds.lmde.proxy-layer"
readonly CANARY_SERVICE="lmde.ollama-gateway.probe-canary"
readonly TOKEN_SERVICE="lmde.ollama-gateway.tunnel-token"
readonly TOKEN_ACCOUNT="ollama-gateway"
readonly CANARY_VALUE="not-a-secret"

# --- Flags / config ---

typeset TREE="" LOGDIR="" AGENTS="" ROUTES="" CANARY_DIR="" DOMAIN=""
typeset -a KEYCHAIN_ARG

load_config() {
    [[ "$(uname -s)" == "Darwin" ]] || { print -r -- "ollama-gateway: macOS only; nothing to do"; exit 0; }
    TREE="${HOME}/.local/share/ollama-gateway"
    LOGDIR="${HOME}/Library/Logs/ollama-gateway"
    AGENTS="${HOME}/Library/LaunchAgents"
    ROUTES="${LMDE_PROXY_ROOT:-${HOME}/.local/share/lmde-proxy}/routes"
    CANARY_DIR="${HOME}/.local/state/ollama-gateway-probe"
    DOMAIN="gui/$(id -u)"
    KEYCHAIN_ARG=()
    [[ -n "${OLLAMA_GATEWAY_KEYCHAIN:-}" ]] && KEYCHAIN_ARG=("${OLLAMA_GATEWAY_KEYCHAIN}")
    return 0
}

log() { print -r -- "ollama-gateway: $*"; }
die() { print -u2 -r -- "ollama-gateway: $*"; exit 1; }

# --- Predicates ---

is_loaded() { launchctl print "${DOMAIN}/$1" >/dev/null 2>&1; }

has_run_token() {
    security find-generic-password -s "${TOKEN_SERVICE}" -a "${TOKEN_ACCOUNT}" "${KEYCHAIN_ARG[@]}" >/dev/null 2>&1
}

# --- Effectful helpers ---

# unload <label> -- boot the job out and wait (bounded) until launchd has
# let go of it, so a bootstrap right after cannot race the old instance.
unload() {
    local label="$1"
    integer tries=0
    is_loaded "${label}" || return 0
    launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
    while is_loaded "${label}" && (( tries < 50 )); do
        sleep 0.1
        tries+=1
    done
}

# render_agent <label> -- the plist template with absolute paths, linted.
render_agent() {
    local label="$1" target="${AGENTS}/$1.plist"
    mkdir -p "${AGENTS}"
    sed -e "s|@TREE@|${TREE}|g" -e "s|@LOGDIR@|${LOGDIR}|g" \
        "${COMPONENT_DIR}/launchd/${label}.plist.in" > "${target}"
    plutil -lint "${target}" >/dev/null || die "rendered plist is invalid: ${target}"
}

install_tree() {
    mkdir -p -m 700 "${TREE}"
    mkdir -p "${TREE}/libexec" "${TREE}/sandbox" "${TREE}/connector" "${TREE}/home/.ollama" "${TREE}/home/tmp"
    cp "${COMPONENT_DIR}"/libexec/* "${TREE}/libexec/"
    chmod 755 "${TREE}"/libexec/*.zsh
    cp "${COMPONENT_DIR}/sandbox/ollama-gateway.sb.in" "${TREE}/sandbox/"
    cp "${COMPONENT_DIR}/sandbox/ollama-gateway.probe.tsv" "${TREE}/sandbox/"
    # The profile is rendered here, not copied: its ephemeral-port block
    # comes from this machine's kernel (libexec/profile-render.zsh).
    /bin/zsh -f "${TREE}/libexec/profile-render.zsh" \
        "${TREE}/sandbox/ollama-gateway.sb.in" "${TREE}/sandbox/ollama-gateway.sb"
    cp "${COMPONENT_DIR}/gateway.env" "${TREE}/gateway.env"
    cp "${COMPONENT_DIR}/connector/config.yml" "${TREE}/connector/config.yml"
    mkdir -p "${LOGDIR}"
    log "installed ${TREE}"
}

install_canaries() {
    mkdir -p "${CANARY_DIR}"
    print -r -- "${CANARY_VALUE}" > "${CANARY_DIR}/canary"
    # The probe finds this item by its attributes and never reads its
    # value, so its access list and partition list do not decide whether
    # the probe passes (Issue#441). -A only states that the value is not
    # a secret. Recreated on every install rather than kept, so every
    # install leaves one item in a known shape. Deleted and re-added,
    # never modified in place -- changing an existing item's access list
    # prompts the user.
    integer stale=0
    while security delete-generic-password -s "${CANARY_SERVICE}" "${KEYCHAIN_ARG[@]}" >/dev/null 2>&1 \
        && (( ++stale < 10 )); do
        :
    done
    security add-generic-password -A -s "${CANARY_SERVICE}" -a "${TOKEN_ACCOUNT}" \
        -w "${CANARY_VALUE}" "${KEYCHAIN_ARG[@]}" >/dev/null
    log "probe canaries in place (${CANARY_DIR}/canary, keychain ${CANARY_SERVICE})"
}

install_route() {
    mkdir -p "${ROUTES}"
    cp "${COMPONENT_DIR}/route/ollama-gateway.cfg" "${ROUTES}/ollama-gateway.cfg"
    cp "${COMPONENT_DIR}/route/ollama-gateway.deadline.http" "${ROUTES}/ollama-gateway.deadline.http"
    cp "${COMPONENT_DIR}/gateway.env" "${ROUTES}/ollama-gateway.env"
    if is_loaded "${PROXY_LABEL}"; then
        launchctl kickstart -k "${DOMAIN}/${PROXY_LABEL}"
        log "route installed; LMDE proxy layer restarted"
    else
        log "route installed in ${ROUTES}; the LMDE proxy layer is not loaded -- lmde install proxy-layer"
    fi
}

load_agents() {
    render_agent "${OLLAMA_LABEL}"
    render_agent "${CONNECTOR_LABEL}"
    unload "${OLLAMA_LABEL}"
    launchctl bootstrap "${DOMAIN}" "${AGENTS}/${OLLAMA_LABEL}.plist"
    log "loaded ${OLLAMA_LABEL}"
    unload "${CONNECTOR_LABEL}"
    if has_run_token; then
        launchctl enable "${DOMAIN}/${CONNECTOR_LABEL}"
        launchctl bootstrap "${DOMAIN}" "${AGENTS}/${CONNECTOR_LABEL}.plist"
        log "loaded ${CONNECTOR_LABEL}"
    else
        launchctl disable "${DOMAIN}/${CONNECTOR_LABEL}"
        log "${CONNECTOR_LABEL} installed but DISABLED: no run token in the keychain yet."
        log "  once the edge is applied, a human seeds it (and is shown the load commands):"
        log "    ${COMPONENT_DIR}/seed-tunnel-token.zsh <op-reference>"
    fi
}

# --- Flows ---

do_install() {
    install_tree
    install_canaries
    install_route
    load_agents
}

do_uninstall() {
    unload "${CONNECTOR_LABEL}"
    unload "${OLLAMA_LABEL}"
    rm -f "${AGENTS}/${OLLAMA_LABEL}.plist" "${AGENTS}/${CONNECTOR_LABEL}.plist"
    rm -f "${ROUTES}/ollama-gateway.cfg" "${ROUTES}/ollama-gateway.deadline.http" "${ROUTES}/ollama-gateway.env"
    if is_loaded "${PROXY_LABEL}"; then
        launchctl kickstart -k "${DOMAIN}/${PROXY_LABEL}"
    fi
    rm -rf "${TREE}" "${CANARY_DIR}"
    security delete-generic-password -s "${CANARY_SERVICE}" -a "${TOKEN_ACCOUNT}" "${KEYCHAIN_ARG[@]}" >/dev/null 2>&1 || true
    log "uninstalled. The run token stays in the keychain; to delete it:"
    log "  security delete-generic-password -s ${TOKEN_SERVICE} -a ${TOKEN_ACCOUNT}"
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
