#!/usr/bin/env bash
# 07_launcher_refuses_a_bound_port.sh
# Given something already listening on the gateway's ollama port, When the
# launcher starts, Then it exits non-zero naming the port and starts
# nothing: the deadline proxy must only ever reach the external ollama.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

LISTENER_PID=""

stop_listener() {
    if [[ -n "${LISTENER_PID}" ]] && kill -0 "${LISTENER_PID}" 2>/dev/null; then
        kill "${LISTENER_PID}" 2>/dev/null || true
    fi
    fixture_cleanup
}

main() {
    require_macos
    fixture_setup
    trap stop_listener EXIT INT TERM HUP
    install_fake_ollama
    OLLAMA_PORT="$(free_port)"
    local out status=0 tries=0

    /usr/bin/python3 -c 'import socket,sys,time; s=socket.socket(); s.bind(("127.0.0.1",int(sys.argv[1]))); s.listen(1); time.sleep(30)' "${OLLAMA_PORT}" &
    LISTENER_PID=$!
    until lsof -nP -iTCP:"${OLLAMA_PORT}" -sTCP:LISTEN >/dev/null 2>&1; do
        tries=$((tries + 1))
        [[ "${tries}" -lt 50 ]] || fail "throwaway listener never bound ${OLLAMA_PORT}"
        sleep 0.1
    done

    out="$(run_launcher)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "launcher must refuse a bound port; output: ${out}"
    assert_contains "${out}" "${OLLAMA_PORT}" "the port is named"
    [[ ! -e "${TREE}/home/fake-ollama.out" ]] || fail "ollama was started onto a bound port"
}

main "$@"
