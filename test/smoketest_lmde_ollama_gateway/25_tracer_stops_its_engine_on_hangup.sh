#!/usr/bin/env bash
# 25_tracer_stops_its_engine_on_hangup.sh
# Given profile-trace.zsh has started its scratch engine (a fake ollama
# that records its pid and waits), When the tracer's terminal hangs up
# (SIGHUP), Then the engine it started is stopped too, so a trace run cut
# short by a closed terminal leaves no extra engine holding the GPU
# (Codex review of PR#462; AGENTS.md on child-process cleanup).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

# install_waiting_ollama -- a fake engine in the keg that writes its pid
# into the tracer's scratch home and then waits, as a loading model would.
install_waiting_ollama() {
    cat > "${FAKE_KEG}/bin/ollama" <<'FAKE'
#!/bin/sh
echo $$ > "${HOME}/fake-ollama.pid"
while :; do sleep 1; done
FAKE
    chmod +x "${FAKE_KEG}/bin/ollama"
}

main() {
    require_macos
    fixture_setup
    install_waiting_ollama
    local out="${WORK}/trace-out" pidfile tracer_pid engine_pid tries=0
    pidfile="${out}/home/fake-ollama.pid"

    env -i HOME="${FAKE_HOME}" PATH="${FAKE_KEG}/bin:${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin" \
        /bin/zsh -f "${TREE}/libexec/profile-trace.zsh" --model fake --out "${out}" --wait 60 \
        > "${WORK}/tracer.log" 2>&1 &
    tracer_pid=$!
    while [[ ! -s "${pidfile}" ]] && (( tries < 100 )); do sleep 0.2; tries=$((tries + 1)); done
    [[ -s "${pidfile}" ]] || fail "the fake engine never started; tracer log:
$(cat "${WORK}/tracer.log")"
    engine_pid="$(cat "${pidfile}")"
    kill -0 "${engine_pid}" 2>/dev/null || fail "fake engine pid ${engine_pid} is not alive before the hangup"

    kill -HUP "${tracer_pid}"
    tries=0
    while kill -0 "${engine_pid}" 2>/dev/null && (( tries < 100 )); do sleep 0.2; tries=$((tries + 1)); done
    if kill -0 "${engine_pid}" 2>/dev/null; then
        kill -9 "${engine_pid}" 2>/dev/null || true
        fail "the fake engine (pid ${engine_pid}) outlived the tracer's hangup; tracer log:
$(cat "${WORK}/tracer.log")"
    fi
    wait "${tracer_pid}" 2>/dev/null || true
}

main "$@"
