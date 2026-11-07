#!/usr/bin/env bash
# 27_launcher_records_the_keg_it_grants.sh
# Given an ollama in its own keg, When the launcher starts the engine, Then
# it records that keg in <tree>/run/engine.keg, the one keg the sandbox
# lets the engine exec from; and When it runs --probe-only, Then it leaves
# the record alone -- a probe on a live laptop does not start an engine,
# so it must not claim the running one was started from the current keg
# (Issue#709: a Homebrew upgrade swapped the keg under a running engine,
# and nothing could tell the two apart).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    OLLAMA_PORT="$(free_port)"
    local out status=0 record="${TREE}/run/engine.keg"

    out="$(run_launcher)" || status=$?
    assert_eq "${status}" "0" "launcher exit status; output: ${out}"
    [[ -f "${record}" ]] || fail "launcher started the engine without recording its keg; output: ${out}"
    assert_eq "$(cat "${record}")" "${FAKE_KEG}" "the recorded keg is the one the profile grants"

    echo "/previous/keg" > "${record}"
    status=0
    out="$(run_launcher /bin/zsh -f "${LAUNCH_OLLAMA}" --probe-only)" || status=$?
    assert_eq "${status}" "0" "probe-only exit status; output: ${out}"
    assert_eq "$(cat "${record}")" "/previous/keg" "probe-only must not rewrite the running engine's keg"
}

main "$@"
