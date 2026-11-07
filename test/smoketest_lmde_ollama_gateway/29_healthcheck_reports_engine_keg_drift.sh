#!/usr/bin/env bash
# 29_healthcheck_reports_engine_keg_drift.sh
# Given an engine that answers on its port, When the keg it was started
# from is gone or is no longer the keg ollama on PATH resolves to (a
# Homebrew upgrade the keg watcher missed), Then the healthcheck reports
# external-ollama DEGRADED naming both kegs and the restart command, since
# every completion would fail (Issue#709). With no record, or a record
# that matches, it stays OK.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    install_fake_curl
    healthy_local
    local out status record="${TREE}/run/engine.keg"
    local -a env_args=(
        "OLLAMA_GATEWAY_TREE=${TREE}"
        "PATH=${FAKE_KEG}/bin:${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin"
    )

    status=0; out="$(run_healthcheck "${env_args[@]}")" || status=$?
    assert_eq "${status}" "0" "no record is healthy; output: ${out}"
    assert_contains "${out}" "external-ollama: OK" "no record"

    mkdir -p "${TREE}/run"
    echo "${FAKE_KEG}" > "${record}"
    status=0; out="$(run_healthcheck "${env_args[@]}")" || status=$?
    assert_eq "${status}" "0" "matching record is healthy; output: ${out}"
    assert_contains "${out}" "external-ollama: OK" "matching record"

    mkdir -p "${WORK}/old-keg/bin"
    echo "${WORK}/old-keg" > "${record}"
    status=0; out="$(run_healthcheck "${env_args[@]}")" || status=$?
    [[ "${status}" -ne 0 ]] || fail "an engine on a superseded keg must be DEGRADED; output: ${out}"
    assert_contains "${out}" "external-ollama: DEGRADED" "superseded keg"
    assert_contains "${out}" "${WORK}/old-keg" "names the engine's keg"
    assert_contains "${out}" "${FAKE_KEG}" "names the current keg"
    assert_contains "${out}" "kickstart -k" "names the restart"

    status=0; out="$(run_healthcheck "OLLAMA_GATEWAY_TREE=${TREE}")" || status=$?
    assert_eq "${status}" "0" "a keg that exists, with no ollama on PATH, is no evidence of drift; output: ${out}"
    assert_contains "${out}" "external-ollama: OK" "existing keg, no ollama on PATH"

    echo "${WORK}/removed-keg" > "${record}"
    status=0; out="$(run_healthcheck "OLLAMA_GATEWAY_TREE=${TREE}")" || status=$?
    [[ "${status}" -ne 0 ]] || fail "an engine whose keg is gone must be DEGRADED, even with no ollama on PATH; output: ${out}"
    assert_contains "${out}" "${WORK}/removed-keg" "names the removed keg"
}

main "$@"
