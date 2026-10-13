#!/usr/bin/env bash
# 26_launcher_probe_only_reports_without_starting.sh
# Given an installed gateway tree, When the launcher is run with
# --probe-only, Then it runs the control and confined probe passes with
# the same parameters it would start ollama with, prints both passes'
# rows, exits 0 when both pass and 78 when either fails, does not refuse
# because the engine's port is bound (on a live laptop the engine holds
# it), accepts no other argument, and never starts ollama -- so a
# smoketest (tds-internal's G6) can re-prove G4 on a running laptop without
# restarting the engine.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

LISTENER_PID=""

stop_listener() {
    if [[ -n "${LISTENER_PID}" ]] && kill -0 "${LISTENER_PID}" 2>/dev/null; then
        kill "${LISTENER_PID}" 2>/dev/null || true
    fi
    fixture_cleanup
}

# assert_line <haystack> <line> <message> -- the whole line is present:
# a confined row carries no tag, so a substring of it also matches the
# control row's "<row> [control]".
assert_line() {
    printf '%s\n' "$1" | grep -qxF -- "$2" || fail "$3: no line '$2' in: $1"
}

# bind_ollama_port -- a throwaway listener on OLLAMA_PORT, as the live
# engine would be.
bind_ollama_port() {
    local tries=0
    /usr/bin/python3 -c 'import socket,sys,time; s=socket.socket(); s.bind(("127.0.0.1",int(sys.argv[1]))); s.listen(1); time.sleep(30)' "${OLLAMA_PORT}" &
    LISTENER_PID=$!
    until lsof -nP -iTCP:"${OLLAMA_PORT}" -sTCP:LISTEN >/dev/null 2>&1; do
        tries=$((tries + 1))
        [[ "${tries}" -lt 50 ]] || fail "throwaway listener never bound ${OLLAMA_PORT}"
        sleep 0.1
    done
}

assert_not_started() {
    [[ ! -e "${TREE}/home/fake-ollama.out" ]] || fail "$1"
}

main() {
    require_macos
    fixture_setup
    trap stop_listener EXIT INT TERM HUP
    install_fake_ollama
    OLLAMA_PORT="$(free_port)"
    local open="${WORK}/open.sb" out status=0
    printf '(version 1)\n(allow default)\n' > "${open}"

    # Both passes hold: both passes' rows, exit 0, no engine.
    out="$(run_launcher /bin/zsh -f "${LAUNCH_OLLAMA}" --probe-only)" || status=$?
    assert_eq "${status}" "0" "probe-only exit status; output: ${out}"
    assert_line "${out}" "ok canary-file-unreadable" "the confined rows are printed"
    assert_line "${out}" "ok canary-file-unreadable [control]" "the control rows are printed"
    assert_contains "${out}" "probe passed" "the verdict is stated"
    assert_not_started "ollama was started under --probe-only"

    # The engine's port is bound, as on a live laptop: not a refusal.
    bind_ollama_port
    status=0
    out="$(run_launcher /bin/zsh -f "${LAUNCH_OLLAMA}" --probe-only)" || status=$?
    assert_eq "${status}" "0" "probe-only exit status with the port bound; output: ${out}"
    [[ "${out}" != *"already bound"* ]] || fail "probe-only refused a bound port: ${out}"
    kill "${LISTENER_PID}"; wait "${LISTENER_PID}" 2>/dev/null || true; LISTENER_PID=""
    assert_not_started "ollama was started beside the listener"

    # Any other argument is refused before the probe runs.
    status=0
    out="$(run_launcher /bin/zsh -f "${LAUNCH_OLLAMA}" --probe)" || status=$?
    assert_eq "${status}" "78" "exit status on an unknown argument; output: ${out}"
    assert_contains "${out}" "usage: launch-ollama.zsh" "the usage is stated"
    status=0
    out="$(run_launcher /bin/zsh -f "${LAUNCH_OLLAMA}" --probe-only extra)" || status=$?
    assert_eq "${status}" "78" "exit status on a second argument; output: ${out}"
    assert_not_started "ollama was started on a refused argument"

    # The confined pass fails (an unconfining profile): the control rows
    # were printed, the failed confined row is named, exit 78.
    status=0
    out="$(run_launcher OLLAMA_GATEWAY_PROFILE="${open}" /bin/zsh -f "${LAUNCH_OLLAMA}" --probe-only)" || status=$?
    assert_eq "${status}" "78" "probe-only exit status on a failed confined pass; output: ${out}"
    assert_line "${out}" "ok canary-file-unreadable [control]" "the control rows are printed before the confined failure"
    assert_contains "${out}" "FAIL canary-file-unreadable" "the failed confined row is named"
    assert_contains "${out}" "G4 probe failed under" "the confined pass is the one blamed"
    assert_not_started "ollama was started after a failed confined pass"

    # The control pass fails (a missing canary): exit 78, the row named.
    rm -f "${CANARY_FILE}"
    status=0
    out="$(run_launcher /bin/zsh -f "${LAUNCH_OLLAMA}" --probe-only)" || status=$?
    assert_eq "${status}" "78" "probe-only exit status on a failed control pass; output: ${out}"
    assert_contains "${out}" "FAIL canary-file-unreadable" "the failed control row is named"
    assert_contains "${out}" "control pass failed" "the control pass is the one blamed"
    assert_not_started "ollama was started after a failed control pass"
}

main "$@"
