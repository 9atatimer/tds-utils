#!/bin/zsh -f
# profile-trace.zsh -- the Ollama Gateway's allow-list apparatus
# (docs/design/OLLAMA-GATEWAY.DESIGN.md, G4; tds-utils Issue#460).
#
# Runs the real `ollama serve` under a CANDIDATE sandbox profile, on a
# scratch port with a scratch HOME, drives the gateway's workload against
# it (version, model list, one short completion), stops it, and prints
# every operation the sandbox denied during the run as the unified log
# recorded it -- then the same lines as SBPL allow rules to paste into the
# profile. The profile is never modified; a human decides what to allow.
# Iterate until the workload passes and the trace is empty.
#
# Usage: profile-trace.zsh --profile <sb> --model <name>
#                          [--store <dir>] [--port <n>] [--out <dir>]
#                          [--wait <seconds>]
#
#   --profile  the candidate profile or template; a template (a file
#              containing @EPHEMERAL_OUTBOUND@) is rendered into --out
#              first (default: sandbox/ollama-gateway.sb.in beside this
#              libexec/)
#   --model    a model in the store the completion uses; small is better
#   --store    the model store (default ~/.ollama/models), read-only here
#   --port     the scratch port (default: a free one)
#   --out      scratch tree (default: a temp dir, kept, named at the end)
#   --wait     seconds to wait for ollama to answer /api/version (default 90)
#
# Side effects: starts one extra ollama for the run (GPU use while the
# model loads), reads the unified log, writes under --out. Never touches
# the installed gateway, the everyday ollama or launchd.
#
# zsh: macOS-only (sandbox-exec, the unified log).

set -euo pipefail

# --- Constants ---

readonly SCRIPT_DIR="${0:A:h}"
readonly COMPONENT_ROOT="${SCRIPT_DIR:h}"
readonly SANDBOX_EXEC="/usr/bin/sandbox-exec"
readonly LOG="/usr/bin/log"
readonly CHILD_PATH="/usr/bin:/bin:/usr/sbin:/sbin"
readonly EX_USAGE=64
readonly EX_CONFIG=78

# --- Flags / config ---

typeset PROFILE="" MODEL="" STORE="" PORT="" OUT="" WAIT=90
typeset OLLAMA_BIN="" HOME_DIR="" STARTED_AT="" PID=""

# --- Reporting ---

log() { print -r -- "profile-trace: $*"; }
die() { print -u2 -r -- "profile-trace: $*"; exit "${2:-${EX_CONFIG}}"; }
usage() { sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; }

# --- Pure helpers ---

# as_sbpl <deny line> -- one unified-log denial as an allow rule. Operations
# with a path target become a literal; mach and sysctl targets a name; the
# rest are left for a human to shape.
as_sbpl() {
    local op="$1" target="$2"
    case "${op}" in
        file-read*|file-write*|file-ioctl|file-map-executable)
            print -r -- "(allow ${op} (literal \"${target}\"))" ;;
        mach-lookup) print -r -- "(allow mach-lookup (global-name \"${target}\"))" ;;
        sysctl-read) print -r -- "(allow sysctl-read (sysctl-name \"${target}\"))" ;;
        process-exec*) print -r -- "(allow ${op} (literal \"${target}\"))" ;;
        network-outbound|network-inbound|network-bind)
            print -r -- ";; ${op} ${target}: write the (remote|local ...) filter by hand" ;;
        *) print -r -- ";; ${op} ${target}: shape by hand" ;;
    esac
}

# --- Effectful helpers ---

free_port() {
    /usr/bin/python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}

http() { curl -sS -m 120 "$@"; }

wait_for_ollama() {
    integer tries=0
    while (( tries < WAIT )); do
        if http -o /dev/null "http://127.0.0.1:${PORT}/api/version" 2>/dev/null; then
            return 0
        fi
        if ! kill -0 "${PID}" 2>/dev/null; then
            log "ollama exited before answering (see ${OUT}/ollama.log); collecting the trace"
            return 1
        fi
        sleep 1
        tries+=1
    done
    return 1
}

start_ollama() {
    mkdir -p "${HOME_DIR}/.ollama" "${HOME_DIR}/tmp"
    STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
    (
        cd "${HOME_DIR}"
        exec "${SANDBOX_EXEC}" -f "${PROFILE}" \
            -D "USER_HOME=${HOME:A}" \
            -D "GATEWAY_TREE=${OUT}/tree" \
            -D "GATEWAY_HOME=${HOME_DIR}" \
            -D "MODEL_STORE=${STORE}" \
            -D "MODEL_STORE_PARENT=${STORE:h}" \
            -D "OLLAMA_KEG=${OLLAMA_BIN:A:h:h}" \
            /usr/bin/env -i \
            HOME="${HOME_DIR}" PATH="${CHILD_PATH}" TMPDIR="${HOME_DIR}/tmp" \
            OLLAMA_HOST="127.0.0.1:${PORT}" OLLAMA_MODELS="${STORE}" \
            OLLAMA_NOPRUNE=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=1m \
            OLLAMA_CONTEXT_LENGTH=4096 OLLAMA_NO_CLOUD=1 \
            OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 \
            "${OLLAMA_BIN}" serve
    ) > "${OUT}/ollama.log" 2>&1 &
    PID=$!
    log "started ollama pid ${PID} on 127.0.0.1:${PORT} under ${PROFILE}"
}

stop_ollama() {
    [[ -n "${PID}" ]] || return 0
    kill "${PID}" 2>/dev/null || true
    integer tries=0
    while kill -0 "${PID}" 2>/dev/null && (( tries < 30 )); do sleep 0.5; tries+=1; done
    if kill -0 "${PID}" 2>/dev/null; then
        kill -9 "${PID}" 2>/dev/null || true
        sleep 1
    fi
    kill -0 "${PID}" 2>/dev/null && die "ollama pid ${PID} would not stop" || log "stopped ollama"
    PID=""
}

workload() {
    local rc=0 body
    log "workload: GET /api/version"
    http -o /dev/null -w 'version -> %{http_code}\n' "http://127.0.0.1:${PORT}/api/version" || rc=1
    log "workload: GET /api/tags, GET /v1/models"
    http -o /dev/null -w 'tags -> %{http_code}\n' "http://127.0.0.1:${PORT}/api/tags" || rc=1
    http -o "${OUT}/models.json" -w 'models -> %{http_code}\n' "http://127.0.0.1:${PORT}/v1/models" || rc=1
    log "workload: POST /v1/chat/completions (${MODEL})"
    body="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK.\"}],\"max_tokens\":4,\"stream\":false}"
    http -o "${OUT}/completion.json" -w 'completion -> %{http_code}\n' \
        -H 'content-type: application/json' -d "${body}" "http://127.0.0.1:${PORT}/v1/chat/completions" || rc=1
    head -c 300 "${OUT}/completion.json" 2>/dev/null; print
    return "${rc}"
}

collect_denials() {
    "${LOG}" show --start "${STARTED_AT}" --style compact --predicate 'sender == "Sandbox"' 2>/dev/null \
        | grep -E 'Sandbox: (ollama|env|python3)\([0-9]+\) deny' \
        | sed -E 's/.*deny\([0-9]+\) //' \
        | sed -E 's/^([a-z*-]+) (.*)$/\1 \2/' \
        | sort -u > "${OUT}/denials.txt" || true
}

report() {
    local n
    n=$(wc -l < "${OUT}/denials.txt" | tr -d ' ')
    print
    log "denied during the run: ${n} distinct operation(s) (${OUT}/denials.txt)"
    cat "${OUT}/denials.txt"
    print
    log "as SBPL allow rules (shape before pasting; never paste a subpath you did not mean):"
    while read -r op target; do as_sbpl "${op}" "${target}"; done < "${OUT}/denials.txt" | sort -u | tee "${OUT}/allow.sbpl"
    print
    log "ollama log: ${OUT}/ollama.log"
}

# --- Entry point ---

parse_args() {
    while (( $# > 0 )); do
        case "$1" in
            --profile) PROFILE="$2"; shift 2 ;;
            --model) MODEL="$2"; shift 2 ;;
            --store) STORE="$2"; shift 2 ;;
            --port) PORT="$2"; shift 2 ;;
            --out) OUT="$2"; shift 2 ;;
            --wait) WAIT="$2"; shift 2 ;;
            -h|--help) usage; exit 0 ;;
            *) usage >&2; die "unknown argument: $1" "${EX_USAGE}" ;;
        esac
    done
    [[ -n "${MODEL}" ]] || { usage >&2; die "--model is required" "${EX_USAGE}"; }
    PROFILE="${${PROFILE:-${COMPONENT_ROOT}/sandbox/ollama-gateway.sb.in}:A}"
    STORE="${${STORE:-${HOME}/.ollama/models}:A}"
    [[ -f "${PROFILE}" ]] || die "profile not found: ${PROFILE}"
    [[ -d "${STORE}" ]] || die "store not found: ${STORE}"
    [[ -n "${PORT}" ]] || PORT="$(free_port)"
    OUT="${${OUT:-$(mktemp -d "${TMPDIR:-/tmp}/ollama-gateway-trace.XXXXXX")}:A}"
    mkdir -p "${OUT}/tree"
    HOME_DIR="${OUT}/home"
    if grep -q -x -- '@EPHEMERAL_OUTBOUND@' "${PROFILE}"; then
        /bin/zsh -f "${SCRIPT_DIR}/profile-render.zsh" "${PROFILE}" "${OUT}/rendered.sb" >&2
        PROFILE="${OUT}/rendered.sb"
    fi
    OLLAMA_BIN="$(whence -p ollama)" || die "ollama not found on PATH"
}

main() {
    parse_args "$@"
    trap stop_ollama EXIT INT TERM
    start_ollama
    if wait_for_ollama; then
        workload || log "workload had failures (expected while the allow-list is incomplete)"
    else
        log "ollama did not answer within ${WAIT}s (expected while the allow-list is incomplete)"
    fi
    stop_ollama
    sleep 3
    collect_denials
    report
}

main "$@"
