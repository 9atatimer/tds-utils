#!/usr/bin/env bash
# 23_probe_control_refuses_a_vacuous_deny.sh
# Given the spec table and no sandbox, When the control pass runs, Then
# every deny row is observed as reachable (permit or allow), and a row
# whose target is unreachable even unconfined fails the control pass --
# so the confined pass can never pass vacuously (a nonexistent path, a
# port nothing could reach).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local args=() line out status=0 spec="${TREE}/home/vacuous.tsv"
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(/bin/zsh -f "${PROBE}" control "${args[@]}" 2>&1)" || status=$?
    assert_eq "${status}" "0" "control pass with the shipped spec; output:
${out}"
    assert_contains "${out}" "ok tmp-write-denied" "control proves /private/tmp is writable unconfined"
    assert_contains "${out}" "ok launchd-unreachable" "control proves launchd is reachable unconfined"
    assert_contains "${out}" "ok outbound-denied" "control proves the outbound target is not refused by anything but a sandbox"

    cp "${COMPONENT_DIR}/sandbox/ollama-gateway.probe.tsv" "${spec}"
    printf 'ghost-unreadable\tdeny\tallow\tread\t%s\n' "${WORK}/no-such-file" >> "${spec}"
    status=0
    out="$(/bin/zsh -f "${PROBE}" control --spec "${spec}" "${args[@]}" 2>&1)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "control must fail a row whose target is unreachable unconfined; output:
${out}"
    assert_contains "${out}" "FAIL ghost-unreadable" "the vacuous row is named"
}

main "$@"
