#!/usr/bin/env bash
# 26_launcher_probe_only_reports_without_starting.sh
# Given an installed gateway tree, When the launcher is run with
# --probe-only, Then it runs the control and confined probe passes with
# the same parameters it would start ollama with, prints their rows, exits
# 0 when both pass and 78 when one fails, and never starts ollama -- so a
# smoketest (tds-internal's G6) can re-prove G4 on a running laptop without
# restarting the engine.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    OLLAMA_PORT="$(free_port)"
    local out status=0

    out="$(run_launcher /bin/zsh -f "${LAUNCH_OLLAMA}" --probe-only)" || status=$?
    assert_eq "${status}" "0" "probe-only exit status; output: ${out}"
    assert_contains "${out}" "ok canary-file-unreadable" "the confined rows are printed"
    assert_contains "${out}" "ok canary-file-unreadable [control]" "the control rows are printed"
    assert_contains "${out}" "probe passed" "the verdict is stated"
    [[ ! -e "${TREE}/home/fake-ollama.out" ]] || fail "ollama was started under --probe-only"

    rm -f "${CANARY_FILE}"
    status=0
    out="$(run_launcher /bin/zsh -f "${LAUNCH_OLLAMA}" --probe-only)" || status=$?
    assert_eq "${status}" "78" "probe-only exit status on a failed control pass; output: ${out}"
    assert_contains "${out}" "FAIL canary-file-unreadable" "the failed row is named"
    [[ ! -e "${TREE}/home/fake-ollama.out" ]] || fail "ollama was started after a failed probe"
}

main "$@"
