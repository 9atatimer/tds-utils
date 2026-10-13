#!/usr/bin/env bash
# 05_launcher_refuses_to_start_unconfined.sh
# Given a profile that confines nothing, When the launcher starts, Then the
# G4 probe fails, the launcher exits non-zero with a message saying it
# refuses to start unconfined, and ollama is never started -- no fallback
# (G7, Rejections). Likewise when the file canary is missing, so the probe
# cannot prove anything: refuse, never pass vacuously.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    OLLAMA_PORT="$(free_port)"
    local open="${WORK}/open.sb" out status=0
    printf '(version 1)\n(allow default)\n' > "${open}"

    out="$(run_launcher OLLAMA_GATEWAY_PROFILE="${open}")" || status=$?
    [[ "${status}" -ne 0 ]] || fail "launcher must refuse an unconfining profile; output:
${out}"
    assert_contains "${out}" "refusing to start" "refusal message"
    assert_contains "${out}" "FAIL canary-file-unreadable" "the failed check is named"
    [[ ! -e "${TREE}/home/fake-ollama.out" ]] || fail "ollama was started despite the failed probe"

    rm -f "${CANARY_FILE}"
    status=0
    out="$(run_launcher)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "launcher must refuse when the canary is missing"
    assert_contains "${out}" "FAIL canary-file-unreadable" "missing canary named"
    [[ ! -e "${TREE}/home/fake-ollama.out" ]] || fail "ollama was started without a canary"
}

main "$@"
