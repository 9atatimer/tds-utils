#!/usr/bin/env bash
# 06_launcher_starts_ollama_confined_and_bounded.sh
# Given the real profile and both canaries, When the launcher starts, Then
# `ollama serve` runs under the profile (it cannot read the file canary or
# ~/.ssh) with HOME = the gateway tree's home, OLLAMA_HOST on loopback at
# the gateway's ollama port, OLLAMA_MODELS = the everyday store, pruning
# off, at most one loaded model, the keep_alive from gateway.env (Q3),
# cloud off -- and nothing else from the launcher's environment.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    OLLAMA_PORT="$(free_port)"
    local out status=0 rec keep_alive
    keep_alive="$(env -i /bin/sh -c ". '${COMPONENT_DIR}/gateway.env'; printf %s \"\${OLLAMA_GATEWAY_KEEP_ALIVE}\"")"
    [[ -n "${keep_alive}" ]] || fail "gateway.env defines no OLLAMA_GATEWAY_KEEP_ALIVE"

    out="$(run_launcher LEAKY_SECRET=do-not-pass)" || status=$?
    assert_eq "${status}" "0" "launcher exit status; output: ${out}"
    [[ -f "${WORK}/fake-ollama.out" ]] || fail "ollama never started; output: ${out}"
    rec="$(cat "${WORK}/fake-ollama.out")"

    assert_contains "${rec}" "argv serve" "runs ollama serve"
    assert_contains "${rec}" "canary denied" "ollama runs confined (file canary)"
    assert_contains "${rec}" "ssh denied" "ollama runs confined (~/.ssh)"
    assert_contains "${rec}" "env HOME=${TREE}/home" "HOME is the gateway tree"
    assert_contains "${rec}" "env OLLAMA_HOST=127.0.0.1:${OLLAMA_PORT}" "loopback on the gateway port"
    assert_contains "${rec}" "env OLLAMA_MODELS=${STORE}" "the everyday store"
    assert_contains "${rec}" "env OLLAMA_NOPRUNE=1" "pruning disabled (G8)"
    assert_contains "${rec}" "env OLLAMA_MAX_LOADED_MODELS=1" "one loaded model"
    assert_contains "${rec}" "env OLLAMA_KEEP_ALIVE=${keep_alive}" "short keep_alive (Q3)"
    assert_contains "${rec}" "env OLLAMA_NO_CLOUD=1" "no cloud inference"
    assert_not_contains "${rec}" "LEAKY_SECRET" "environment scrubbed"
    assert_not_contains "${rec}" "OLLAMA_GATEWAY_PROBE_KEYCHAIN" "launcher config not passed on"
    assert_not_contains "${rec}" "11434" "never the everyday port"
    assert_contains "${out}" "probe passed" "launcher logs the probe result"
}

main "$@"
