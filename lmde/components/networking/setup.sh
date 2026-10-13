#!/usr/bin/env bash
# setup.sh -- install the LMDE networking component's host edge: Caddy's
# configuration (lmde/components/networking/README.md; tds-utils Issue#465).
#
# Usage: setup.sh [install]     (default: install)
#
# install (idempotent):
#   - creates the component's run dir, ~/.local/share/lmde-networking/run,
#     mode 0700, where Caddy's admin socket lives
#   - renders caddy/Caddyfile.in into Homebrew's Caddyfile
#     (/opt/homebrew/etc/Caddyfile), admin API on that socket, mode 0600
#   - restarts the Homebrew Caddy service so the socket replaces the TCP
#     endpoint (brew services restart caddy)
#
# Caddy's routes are not here: lib.sh adds them through the admin API when
# a cluster bootstraps. A human runs this; it changes what the laptop's
# reverse proxy listens on for administration.
#
# Environment (tests only): LMDE_NETWORKING_CADDY_ETC, the directory to
# render the Caddyfile into; LMDE_NETWORKING_NO_RESTART=1, skip the
# service restart.

set -euo pipefail

COMPONENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${COMPONENT_DIR}/caddy/Caddyfile.in"
RUN_DIR="${HOME}/.local/share/lmde-networking/run"
CADDY_ETC="${LMDE_NETWORKING_CADDY_ETC:-/opt/homebrew/etc}"

log() { echo "[networking] $*"; }
die() { echo "[networking] $*" >&2; exit 1; }

# --- Helper functions ---

make_run_dir() {
    mkdir -p "${RUN_DIR}"
    chmod 700 "${RUN_DIR}"
    log "run dir ${RUN_DIR} (mode 0700)"
}

# render_caddyfile -- the template with the run dir filled in, written
# atomically into CADDY_ETC.
render_caddyfile() {
    local target="${CADDY_ETC}/Caddyfile" tmp
    [[ -f "${TEMPLATE}" ]] || die "template not found: ${TEMPLATE}"
    [[ -d "${CADDY_ETC}" ]] || die "Caddy etc dir not found: ${CADDY_ETC} (brew install caddy)"
    tmp="$(mktemp "${CADDY_ETC}/Caddyfile.XXXXXX")"
    sed -e "s|@RUN@|${RUN_DIR}|g" "${TEMPLATE}" > "${tmp}"
    mv -f -- "${tmp}" "${target}"
    log "installed ${target}: admin API on ${RUN_DIR}/caddy-admin.sock"
}

restart_caddy() {
    if [[ "${LMDE_NETWORKING_NO_RESTART:-}" == 1 ]]; then
        log "restart skipped (LMDE_NETWORKING_NO_RESTART=1)"
        return 0
    fi
    if ! command -v brew >/dev/null 2>&1; then
        log "brew not found; restart Caddy yourself so it picks up the Caddyfile"
        return 0
    fi
    brew services restart caddy >/dev/null
    log "restarted the Homebrew Caddy service"
}

# --- Main orchestrator ---

main() {
    case "${1:-install}" in
        install) make_run_dir; render_caddyfile; restart_caddy ;;
        *) die "usage: setup.sh [install]" ;;
    esac
}

main "$@"
