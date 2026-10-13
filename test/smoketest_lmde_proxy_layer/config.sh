#!/usr/bin/env bash
# config.sh -- shared fixtures for the LMDE proxy layer smoke tests
# (lmde/components/proxy-layer) and its first tenant, the Ollama Gateway's
# deadline route (lmde/components/ollama-gateway/route,
# docs/design/OLLAMA-GATEWAY.DESIGN.md, Deadline proxy).
#
# Real HAProxy, started through the layer's own launcher against a
# throwaway root, in front of fake_upstream.py standing in for ollama.
# The deadline is shortened to 1 s so the deadline path runs in about a
# second; that wait is the behavior under test, not a sleep.
#
# Skips when HAProxy is not installed (CI runners) or not on macOS. Nothing
# here touches ~/.local/share/lmde-proxy, launchd or a real ollama.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${TEST_DIR}/../.." && pwd)"
PROXY_DIR="${REPO_DIR}/lmde/components/proxy-layer"
GATEWAY_DIR="${REPO_DIR}/lmde/components/ollama-gateway"
LAUNCH_PROXY="${PROXY_DIR}/libexec/launch-proxy.zsh"
FAKE_UPSTREAM="${TEST_DIR}/fake_upstream.py"

ROOT=""
PROXY_PID=""
UPSTREAM_PID=""
PROXY_PORT=""
UPSTREAM_PORT=""
PROXY_LOG=""
RECORD=""

# --- Platform gate -----------------------------------------------------------

require_haproxy() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        echo "skip: not macOS"
        exit 0
    fi
    if ! command -v haproxy >/dev/null 2>&1; then
        echo "skip: haproxy not installed"
        exit 0
    fi
}

# --- Fixture -----------------------------------------------------------------

stop_pid() {
    local pid="$1" tries=0
    [[ -n "${pid}" ]] || return 0
    kill "${pid}" 2>/dev/null || return 0
    while kill -0 "${pid}" 2>/dev/null; do
        tries=$((tries + 1))
        [[ "${tries}" -lt 50 ]] || { kill -9 "${pid}" 2>/dev/null || true; break; }
        sleep 0.05
    done
}

fixture_cleanup() {
    stop_pid "${PROXY_PID}"
    stop_pid "${UPSTREAM_PID}"
    [[ -n "${ROOT}" && -d "${ROOT}" ]] && rm -rf "${ROOT}"
    return 0
}

free_port() {
    /usr/bin/python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}

# fixture_setup -- a throwaway layer root (short path: unix socket paths are
# capped near 100 bytes) with the gateway's route installed the way the
# gateway's setup.sh installs it.
fixture_setup() {
    ROOT="$(cd "$(mktemp -d /tmp/lmdeproxy.XXXXXX)" && pwd -P)"
    trap fixture_cleanup EXIT INT TERM HUP
    mkdir -p "${ROOT}/routes"
    cp "${GATEWAY_DIR}/route/ollama-gateway.cfg" "${ROOT}/routes/ollama-gateway.cfg"
    cp "${GATEWAY_DIR}/route/ollama-gateway.deadline.http" "${ROOT}/routes/ollama-gateway.deadline.http"
    cp "${GATEWAY_DIR}/gateway.env" "${ROOT}/routes/ollama-gateway.env"
    PROXY_PORT="$(free_port)"
    UPSTREAM_PORT="$(free_port)"
    PROXY_LOG="${ROOT}/haproxy.log"
    RECORD="${ROOT}/upstream.record"
}

# wait_until <command...> -- poll a condition, bounded at 5 s; returns 1 on
# timeout. Event coordination for real processes, never a fixed sleep.
wait_until() {
    local tries=0
    until "$@" >/dev/null 2>&1; do
        tries=$((tries + 1))
        [[ "${tries}" -lt 100 ]] || return 1
        sleep 0.05
    done
}

# wait_for <description> <command...> -- wait_until, failing the test on timeout.
wait_for() {
    local what="$1"
    shift
    wait_until "$@" || fail "timed out waiting for ${what}"
}

port_listening() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN
}

# start_proxy -- the layer's launcher, as launchd runs it, with the route's
# deadline shortened to 1 s and the hold to 10 s.
start_proxy() {
    env -i HOME="${HOME}" PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin" \
        LMDE_PROXY_ROOT="${ROOT}" \
        OLLAMA_GATEWAY_PROXY_PORT="${PROXY_PORT}" \
        OLLAMA_GATEWAY_OLLAMA_PORT="${UPSTREAM_PORT}" \
        OLLAMA_GATEWAY_DEADLINE=1s \
        OLLAMA_GATEWAY_HOLD=10s \
        /bin/zsh -f "${LAUNCH_PROXY}" > "${PROXY_LOG}" 2>&1 &
    PROXY_PID=$!
    wait_until port_listening "${PROXY_PORT}" \
        || fail "the proxy never listened on ${PROXY_PORT}; its output:
$(cat "${PROXY_LOG}" 2>/dev/null)"
}


# start_upstream <mode> [<seconds>] -- the fake ollama on UPSTREAM_PORT
# (fake_upstream.py documents the modes).
start_upstream() {
    local mode="$1" seconds="${2:-0}"
    /usr/bin/python3 "${FAKE_UPSTREAM}" "${UPSTREAM_PORT}" "${mode}" "${RECORD}" "${seconds}" &
    UPSTREAM_PID=$!
    wait_for "the fake upstream" test -f "${RECORD}.ready"
}

# --- Assertions --------------------------------------------------------------

fail() {
    echo "FAIL: $*"
    exit 1
}

assert_eq() {
    local got="$1" want="$2" msg="${3:-}"
    [[ "${got}" == "${want}" ]] || fail "${msg}: got '${got}', want '${want}'"
}

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    [[ "${haystack}" == *"${needle}"* ]] || fail "${msg}: expected '${needle}' in:
${haystack}"
}
