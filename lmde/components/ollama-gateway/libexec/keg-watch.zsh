#!/bin/zsh -f
# keg-watch.zsh -- restart the Ollama Gateway's engine when the keg it was
# started from is no longer the keg `ollama` resolves to (Issue#709).
#
# Run by launchd (com.tds.lmde.ollama-gateway.keg-watch) whenever the
# directory holding `ollama` or the directory holding its kegs changes:
# the two places a Homebrew upgrade relinks and cleans up. Never on a
# clock. A running engine keeps the keg its profile was rendered with; once
# an upgrade deletes that keg, every completion fails to exec the runner
# (HTTP 500) until the engine restarts. `launchctl kickstart -k` restarts
# it, and the launcher re-derives the keg and re-runs the G4 probe.
#
# Always exits 0: every case but a changed keg is a no-op, and a failed
# kickstart is logged for `lmde status` to surface, not retried here.
#
# Environment (optional): OLLAMA_GATEWAY_TREE, the gateway tree
# (default ~/.local/share/ollama-gateway).

set -euo pipefail

# --- Constants ---

readonly SCRIPT_DIR="${0:A:h}"
readonly OLLAMA_LABEL="com.tds.lmde.ollama-gateway.ollama"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/keg.zsh"

# --- Reporting ---

log() { print -r -- "keg-watch: $*"; }

# --- Predicates ---

# is_loaded <label> -- is the agent loaded in this user's GUI domain?
is_loaded() { launchctl print "gui/$(id -u)/$1" >/dev/null 2>&1; }

# --- Flow ---

restart_if_keg_changed() {
    local tree="$1" recorded current
    recorded="$(recorded_engine_keg "${tree}")" || return 0
    if ! current="$(ollama_keg)"; then
        log "ollama not on PATH (${PATH}); waiting for the next change"
        return 0
    fi
    [[ "${recorded}" != "${current}" ]] || return 0
    if ! is_loaded "${OLLAMA_LABEL}"; then
        log "keg changed (${recorded} -> ${current}) but ${OLLAMA_LABEL} is not loaded; nothing to restart"
        return 0
    fi
    log "engine keg ${recorded} superseded by ${current}; restarting ${OLLAMA_LABEL}"
    launchctl kickstart -k "gui/$(id -u)/${OLLAMA_LABEL}" \
        || log "kickstart failed; run: launchctl kickstart -k gui/$(id -u)/${OLLAMA_LABEL}"
}

# --- Entry point ---

main() {
    restart_if_keg_changed "${${OLLAMA_GATEWAY_TREE:-${HOME}/.local/share/ollama-gateway}:A}"
}

main "$@"
