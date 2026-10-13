#!/bin/zsh -f
# launch-ollama.zsh -- start the Ollama Gateway's external ollama under the
# gateway's sandbox profile, or refuse (docs/design/OLLAMA-GATEWAY.DESIGN.md:
# External ollama, G4, G7, G8; Key Decisions Q3, Q7).
#
# Run by launchd (com.tds.lmde.ollama-gateway.ollama), which restarts it
# after a non-zero exit. Before EVERY start it runs the G4 probe: once
# unconfined (the canaries must be reachable) and once under the same
# profile and parameters ollama gets (every denial must hold). If either
# fails, it exits 78 and never starts ollama -- there is no fallback to
# running unconfined; the gateway stays DEGRADED until the probe passes.
#
# Environment (all optional; launchd sets none but HOME and PATH):
#   OLLAMA_GATEWAY_TREE            gateway config tree
#                                  (default ~/.local/share/ollama-gateway)
#   OLLAMA_GATEWAY_MODEL_STORE     the everyday store (default ~/.ollama/models)
#   OLLAMA_GATEWAY_PROFILE         sandbox profile (default: beside libexec/)
#   OLLAMA_GATEWAY_PROBE_SPEC      the probe's conformance table (default:
#                                  beside the profile)
#   OLLAMA_GATEWAY_PROBE_KEYCHAIN  keychain file holding the canary item
#                                  (default: the user's search list)
#   and gateway.env's values (ports, keep_alive, context length).
#
# zsh: macOS-only by nature (sandbox-exec, launchd), per AGENT.md.

set -euo pipefail
zmodload zsh/net/tcp

# --- Constants ---

readonly SCRIPT_DIR="${0:A:h}"
readonly COMPONENT_ROOT="${SCRIPT_DIR:h}"
readonly PROBE="${SCRIPT_DIR}/probe.zsh"
readonly SANDBOX_EXEC="/usr/bin/sandbox-exec"
readonly CANARY_SERVICE="lmde.ollama-gateway.probe-canary"
readonly EVERYDAY_PORT="11434"
readonly EX_CONFIG=78
readonly CHILD_PATH="/usr/bin:/bin:/usr/sbin:/sbin"

# --- Flags / config (read once by load_config) ---

typeset USER_HOME="" TREE="" GATEWAY_HOME="" STORE="" PROFILE="" SPEC="" CANARY_FILE=""
typeset USER_TMPDIR="" PROBE_KEYCHAIN="" OLLAMA_BIN="" OLLAMA_KEG=""
typeset -a SANDBOX_ARGV

# --- Reporting ---

log() { print -r -- "launch-ollama: $*"; }
die() { print -u2 -r -- "launch-ollama: $*"; exit "${EX_CONFIG}"; }

# --- Predicates ---

# is_port_bound <port> -- does anything accept connections on 127.0.0.1:<port>?
is_port_bound() {
    if ztcp 127.0.0.1 "$1" 2>/dev/null; then
        ztcp -c "${REPLY}"
        return 0
    fi
    return 1
}

# --- Pure helpers ---

# probe_args -- the probe's arguments for this configuration.
probe_args() {
    local -a args=(
        --canary-file "${CANARY_FILE}"
        --keychain-service "${CANARY_SERVICE}"
        --store "${STORE}"
        --guard-dir "${TREE}/libexec"
        --gateway-home "${GATEWAY_HOME}"
        --user-tmpdir "${USER_TMPDIR}"
        --deny-port "${EVERYDAY_PORT}"
        --proxy-port "${OLLAMA_GATEWAY_PROXY_PORT}"
        --spec "${SPEC}"
    )
    [[ -n "${PROBE_KEYCHAIN}" ]] && args+=(--keychain "${PROBE_KEYCHAIN}")
    print -r -l -- "${args[@]}"
}

# --- Configuration ---

load_config() {
    # shellcheck disable=SC1091
    source "${COMPONENT_ROOT}/gateway.env"
    [[ -n "${HOME:-}" && -d "${HOME}" ]] || die "HOME is not set to a directory"
    USER_HOME="${HOME:A}"
    TREE="${${OLLAMA_GATEWAY_TREE:-${USER_HOME}/.local/share/ollama-gateway}:A}"
    GATEWAY_HOME="${TREE}/home"
    STORE="${${OLLAMA_GATEWAY_MODEL_STORE:-${USER_HOME}/.ollama/models}:A}"
    PROFILE="${OLLAMA_GATEWAY_PROFILE:-${COMPONENT_ROOT}/sandbox/ollama-gateway.sb}"
    # The G4 conformance table, beside the profile it proves.
    SPEC="${OLLAMA_GATEWAY_PROBE_SPEC:-${COMPONENT_ROOT}/sandbox/ollama-gateway.probe.tsv}"
    # The user's per-session temp tree: unreadable to the engine (G4).
    USER_TMPDIR="${$(getconf DARWIN_USER_TEMP_DIR 2>/dev/null):-/private/var/folders}"
    USER_TMPDIR="${USER_TMPDIR%/}"
    CANARY_FILE="${USER_HOME}/.local/state/ollama-gateway-probe/canary"
    PROBE_KEYCHAIN="${OLLAMA_GATEWAY_PROBE_KEYCHAIN:-}"
    # The keg: the tree the resolved binary lives in (<keg>/bin/ollama, with
    # the real binary and its runner under <keg>/libexec), the one tree the
    # profile lets the engine exec from.
    OLLAMA_BIN="$(whence -p ollama)" || die "ollama not found on PATH (${PATH})"
    OLLAMA_KEG="${OLLAMA_BIN:A:h:h}"
    SANDBOX_ARGV=(
        "${SANDBOX_EXEC}" -f "${PROFILE}"
        -D "USER_HOME=${USER_HOME}"
        -D "GATEWAY_TREE=${TREE}"
        -D "GATEWAY_HOME=${GATEWAY_HOME}"
        -D "MODEL_STORE=${STORE}"
        -D "MODEL_STORE_PARENT=${STORE:h}"
        -D "OLLAMA_KEG=${OLLAMA_KEG}"
    )
}

# --- Preflight: fail fast, name the reason ---

preflight() {
    [[ -x "${SANDBOX_EXEC}" ]] || die "${SANDBOX_EXEC} not found; cannot confine ollama"
    [[ -f "${PROFILE}" ]] || die "sandbox profile not found: ${PROFILE}"
    [[ -f "${SPEC}" ]] || die "probe spec not found: ${SPEC}; run setup.sh"
    [[ -d "${GATEWAY_HOME}" ]] || die "gateway home not found: ${GATEWAY_HOME}; run setup.sh"
    [[ -d "${STORE}" ]] || die "model store not found: ${STORE}"
    [[ "${OLLAMA_GATEWAY_OLLAMA_PORT}" == <1-65535> ]] \
        || die "OLLAMA_GATEWAY_OLLAMA_PORT must be 1-65535, got: ${OLLAMA_GATEWAY_OLLAMA_PORT}"
    [[ "${OLLAMA_GATEWAY_OLLAMA_PORT}" != "${EVERYDAY_PORT}" ]] \
        || die "OLLAMA_GATEWAY_OLLAMA_PORT is the everyday ollama's ${EVERYDAY_PORT}; refusing"
    [[ -d "${OLLAMA_KEG}" ]] || die "ollama keg not found: ${OLLAMA_KEG}"
    if is_port_bound "${OLLAMA_GATEWAY_OLLAMA_PORT}"; then
        die "127.0.0.1:${OLLAMA_GATEWAY_OLLAMA_PORT} is already bound by another process; refusing to start beside it"
    fi
}

# --- Flow: the G4 gate ---

# run_probe -- control unconfined, then confined under the profile. Exits
# EX_CONFIG with the probe's report when either pass fails.
run_probe() {
    local -a args
    local report
    args=("${(@f)$(probe_args)}")
    if ! report="$(/bin/zsh -f "${PROBE}" control "${args[@]}" 2>&1)"; then
        print -u2 -r -- "${report}"
        die "refusing to start the external ollama: the probe's control pass failed (DEGRADED)"
    fi
    if ! report="$(cd "${GATEWAY_HOME}" && "${SANDBOX_ARGV[@]}" /bin/zsh -f "${PROBE}" confined "${args[@]}" 2>&1)"; then
        print -u2 -r -- "${report}"
        die "refusing to start the external ollama unconfined: the G4 probe failed under ${PROFILE} (DEGRADED)"
    fi
    log "probe passed under ${PROFILE}"
}

# --- Flow: start ---

start_ollama() {
    mkdir -p "${GATEWAY_HOME}/tmp"
    cd "${GATEWAY_HOME}"
    log "starting ${OLLAMA_BIN} serve on 127.0.0.1:${OLLAMA_GATEWAY_OLLAMA_PORT} (store ${STORE}, keep_alive ${OLLAMA_GATEWAY_KEEP_ALIVE})"
    exec "${SANDBOX_ARGV[@]}" /usr/bin/env -i \
        HOME="${GATEWAY_HOME}" \
        PATH="${CHILD_PATH}" \
        TMPDIR="${GATEWAY_HOME}/tmp" \
        OLLAMA_HOST="127.0.0.1:${OLLAMA_GATEWAY_OLLAMA_PORT}" \
        OLLAMA_MODELS="${STORE}" \
        OLLAMA_NOPRUNE=1 \
        OLLAMA_MAX_LOADED_MODELS=1 \
        OLLAMA_KEEP_ALIVE="${OLLAMA_GATEWAY_KEEP_ALIVE}" \
        OLLAMA_CONTEXT_LENGTH="${OLLAMA_GATEWAY_CONTEXT_LENGTH}" \
        OLLAMA_NO_CLOUD=1 \
        OLLAMA_FLASH_ATTENTION=1 \
        OLLAMA_KV_CACHE_TYPE=q8_0 \
        "${OLLAMA_BIN}" serve
}

# --- Entry point ---

main() {
    (( $# == 0 )) || die "takes no arguments"
    load_config
    preflight
    run_probe
    start_ollama
}

main "$@"
