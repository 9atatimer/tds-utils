#!/usr/bin/env bash
# 22_probe_is_driven_by_its_spec_table.sh
# Given a spec table with one extra row the profile does not satisfy (a
# read of the model store expected to be denied), When the probe runs
# confined with that table, Then it fails exactly that row and names it --
# so a property is added to the seam by adding a line, and a row the
# profile does not deliver can never read as held.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local spec="${TREE}/home/extra.tsv" args=() line out status=0
    cp "${COMPONENT_DIR}/sandbox/ollama-gateway.probe.tsv" "${spec}"
    printf 'store-unreadable-extra\tdeny\tallow\tlist\t$STORE\n' >> "${spec}"
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(sandboxed /bin/zsh -f "${PROBE}" confined --spec "${spec}" "${args[@]}" 2>&1)" || status=$?

    [[ "${status}" -ne 0 ]] || fail "probe must fail a row the profile does not satisfy; output:
${out}"
    assert_contains "${out}" "FAIL store-unreadable-extra" "the extra row is exercised and fails"
    assert_contains "${out}" "ok store-readable" "the standard rows still run"
    assert_contains "${out}" "ok canary-file-unreadable" "the standard rows still run"
    [[ "$(grep -c '^FAIL ' <<< "${out}")" -eq 1 ]] || fail "exactly one row should fail; output:
${out}"
}

main "$@"
