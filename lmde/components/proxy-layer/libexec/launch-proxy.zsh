#!/bin/zsh -f
# launch-proxy.zsh -- run the LMDE proxy layer: HAProxy with the shared
# haproxy.cfg and every installed tenant route (lmde/components/proxy-layer).
#
# Run by launchd (com.tds.lmde.proxy-layer), which restarts it after a
# non-zero exit. Layout under LMDE_PROXY_ROOT (default
# ~/.local/share/lmde-proxy):
#
#   routes/<tenant>.cfg   a tenant's route: one loopback listener (Q12)
#   routes/<tenant>.env   POSIX sh assignments the route reads as ${VAR}
#   routes/<tenant>.*     anything else the route references (errorfiles)
#   run/                  the layer's unix sockets (mode 700)
#
# Exports LMDE_PROXY_ROOT, LMDE_PROXY_ROUTES and LMDE_PROXY_RUN, sources
# every routes/*.env with export on, validates the whole configuration,
# then execs haproxy in the foreground. Refuses (exit 78) with no routes,
# no haproxy, or an invalid configuration.
#
# zsh: macOS-only (launchd), per AGENT.md.

set -euo pipefail
setopt null_glob

# --- Constants ---

readonly SCRIPT_DIR="${0:A:h}"
readonly LAYER_CFG="${SCRIPT_DIR:h}/haproxy.cfg"
readonly EX_CONFIG=78

# --- Reporting ---

log() { print -r -- "launch-proxy: $*"; }
die() { print -u2 -r -- "launch-proxy: $*"; exit "${EX_CONFIG}"; }

# --- Flow ---

load_routes() {
    local -a envs
    LMDE_PROXY_ROOT="${${LMDE_PROXY_ROOT:-${HOME}/.local/share/lmde-proxy}:A}"
    LMDE_PROXY_ROUTES="${LMDE_PROXY_ROOT}/routes"
    LMDE_PROXY_RUN="${LMDE_PROXY_ROOT}/run"
    export LMDE_PROXY_ROOT LMDE_PROXY_ROUTES LMDE_PROXY_RUN
    [[ -f "${LAYER_CFG}" ]] || die "layer configuration not found: ${LAYER_CFG}"
    local -a routes=("${LMDE_PROXY_ROUTES}"/*.cfg)
    (( ${#routes} > 0 )) || die "no routes installed in ${LMDE_PROXY_ROUTES}; install a tenant (e.g. lmde install ollama-gateway)"
    envs=("${LMDE_PROXY_ROUTES}"/*.env)
    setopt all_export
    local f
    for f in "${envs[@]}"; do
        # shellcheck disable=SC1090
        source "${f}"
    done
    unsetopt all_export
    mkdir -p -m 700 "${LMDE_PROXY_RUN}"
    log "routes: ${(j:, :)${routes[@]:t:r}}"
}

main() {
    (( $# == 0 )) || die "takes no arguments"
    local haproxy
    haproxy="$(whence -p haproxy)" || die "haproxy not found on PATH (${PATH})"
    load_routes
    "${haproxy}" -c -q -f "${LAYER_CFG}" -f "${LMDE_PROXY_ROUTES}" \
        || die "configuration invalid: ${LAYER_CFG} + ${LMDE_PROXY_ROUTES}"
    exec "${haproxy}" -db -f "${LAYER_CFG}" -f "${LMDE_PROXY_ROUTES}"
}

main "$@"
