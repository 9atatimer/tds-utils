#!/usr/bin/env bash
# 24_launcher_refuses_a_shared_keg.sh
# Given an `ollama` that is a regular file in a shared bin directory (a
# manual install in <prefix>/bin, beside other tools), When the launcher
# derives the keg it will let the engine exec and read, Then it refuses
# (exit 78) naming the directory, and never starts ollama: the keg grant
# must cover the engine's own tree only, never a whole prefix
# (self-review of PR#462, finding S3).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    OLLAMA_PORT="$(free_port)"
    # A shared prefix: the fake engine beside another tool in <prefix>/bin.
    local prefix="${WORK}/prefix" out status=0
    mkdir -p "${prefix}/bin"
    cp "${FAKE_KEG}/bin/ollama" "${prefix}/bin/ollama"
    printf '#!/bin/sh\n' > "${prefix}/bin/other-tool"
    chmod +x "${prefix}/bin/other-tool"

    out="$(env -i HOME="${FAKE_HOME}" PATH="${prefix}/bin:${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin" \
        OLLAMA_GATEWAY_PROBE_KEYCHAIN="${KEYCHAIN}" \
        OLLAMA_GATEWAY_OLLAMA_PORT="${OLLAMA_PORT}" \
        /bin/zsh -f "${LAUNCH_OLLAMA}" 2>&1)" || status=$?

    assert_eq "${status}" "78" "launcher exit status (EX_CONFIG); output: ${out}"
    assert_contains "${out}" "${prefix}" "the refusal names the shared directory"
    assert_contains "${out}" "keg" "the refusal says what a keg is expected to be"
    [[ ! -e "${TREE}/home/fake-ollama.out" ]] || fail "ollama was started from a shared prefix"
}

main "$@"
