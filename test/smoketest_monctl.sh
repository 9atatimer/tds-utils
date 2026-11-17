#!/usr/bin/env bash
# smoketest_monctl.sh -- bin/monctl reads the Dell U2725QE's input and flips
# between the home Mac (Thunderbolt) and the work Mac (DisplayPort), whether
# m1ddc reports the input as the bare VCP value or with a high byte set
# (m1ddc 1.3.1 on 2026-11-17: 0x1919 on Thunderbolt, 0x190F on DisplayPort;
# Issue#817).
#
# Hermetic: a fake `m1ddc` goes first on PATH; it reports the input
# FAKE_INPUT and records every `set input`. No monitor is touched.
#
# Usage: ./test/smoketest_monctl.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"

# --- Test harness ---

pass=0
fail=0

ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

# --- Fixtures ---

SCRATCH=""

cleanup() {
    [[ -n ${SCRATCH} ]] && rm -rf "${SCRATCH}"
}

make_fakes() {
    SCRATCH="$(mktemp -d)"
    trap cleanup EXIT
    mkdir -p "${SCRATCH}/bin"

    # m1ddc: lists the panel as display 2 (index 1 is another screen, as on
    # the owner's desk), answers `get input` with FAKE_INPUT, and appends
    # the value of every `set input` to FAKE_SETS.
    cat >"${SCRATCH}/bin/m1ddc" <<'SH'
#!/usr/bin/env bash
case "$*" in
    "display list")
        echo "[1] Unknown Display (37D8832A-0000-0000-0000-000000000000)"
        echo "[2] DELL U2725QE (409126F8-0000-0000-0000-000000000000)" ;;
    "display 2 get input") echo "${FAKE_INPUT}" ;;
    "display 2 set input "*) echo "${@: -1}" >>"${FAKE_SETS}" ;;
    *) exit 9 ;;
esac
SH
    chmod +x "${SCRATCH}/bin/m1ddc"
}

# run_monctl <input m1ddc reports> <args...>: runs monctl the way the Flip
# Monitor app does (`monctl flip`, by name on PATH); output in OUT, every
# input it set in SETS (space-separated).
run_monctl() {
    local input=$1; shift
    : >"${SCRATCH}/sets"
    OUT=$(PATH="${SCRATCH}/bin:${REPO_DIR}/bin:${PATH}" \
        FAKE_INPUT="${input}" FAKE_SETS="${SCRATCH}/sets" \
        monctl "$@" 2>&1) || true
    SETS=$(tr '\n' ' ' <"${SCRATCH}/sets" | sed 's/ $//')
}

# --- Cases ---

# Given the panel on Thunderbolt, reported with a high byte (0x1919),
# When the owner flips, Then it switches to the work Mac's DisplayPort.
test_flip_from_thunderbolt_with_a_high_byte_goes_to_the_work_mac() {
    run_monctl 6425 flip
    [[ ${SETS} == 15 ]] && ok || bad "flip from 0x1919 set '${SETS}', want 15 (DisplayPort); output: ${OUT}"
}

# Given the panel on DisplayPort, reported with a high byte (0x190F),
# When the owner flips, Then it switches to the home Mac's Thunderbolt.
test_flip_from_displayport_with_a_high_byte_goes_home() {
    run_monctl 6415 flip
    [[ ${SETS} == 25 ]] && ok || bad "flip from 0x190F set '${SETS}', want 25 (Thunderbolt); output: ${OUT}"
}

# Given an m1ddc that reports the bare value, When the owner flips,
# Then both directions still work.
test_flip_with_the_bare_value_still_works_both_ways() {
    run_monctl 25 flip
    [[ ${SETS} == 15 ]] && ok || bad "flip from bare 25 set '${SETS}', want 15; output: ${OUT}"
    run_monctl 15 flip
    [[ ${SETS} == 25 ]] && ok || bad "flip from bare 15 set '${SETS}', want 25; output: ${OUT}"
}

# Given the input reported with a high byte, When the owner asks for status,
# Then it names the input and sets nothing.
test_status_names_the_input_with_a_high_byte() {
    run_monctl 6425 status
    [[ ${OUT} == "home (Thunderbolt)" && -z ${SETS} ]] && ok || bad "status of 0x1919 printed '${OUT}', set '${SETS}'"
    run_monctl 6415 status
    [[ ${OUT} == "work (DisplayPort)" && -z ${SETS} ]] && ok || bad "status of 0x190F printed '${OUT}', set '${SETS}'"
}

# Given the panel on HDMI, When the owner flips, Then it goes home.
test_flip_from_hdmi_goes_home() {
    run_monctl 17 flip
    [[ ${SETS} == 25 ]] && ok || bad "flip from HDMI set '${SETS}', want 25; output: ${OUT}"
}

# Given a value that is no known input even after masking (0x1963),
# When the owner flips, Then monctl refuses, names the value, exits
# non-zero (the app's "failed" notification) and switches nothing.
test_flip_refuses_an_unrecognised_input() {
    local status=0
    : >"${SCRATCH}/sets"
    OUT=$(PATH="${SCRATCH}/bin:${REPO_DIR}/bin:${PATH}" \
        FAKE_INPUT=6499 FAKE_SETS="${SCRATCH}/sets" \
        monctl flip 2>&1) || status=$?
    SETS=$(tr '\n' ' ' <"${SCRATCH}/sets" | sed 's/ $//')
    [[ ${status} -ne 0 && -z ${SETS} && ${OUT} == *0x1963* ]] && ok \
        || bad "flip of unknown 0x1963 exited ${status}, set '${SETS}', printed '${OUT}'"
}

# --- Main ---

main() {
    make_fakes
    test_flip_from_thunderbolt_with_a_high_byte_goes_to_the_work_mac
    test_flip_from_displayport_with_a_high_byte_goes_home
    test_flip_with_the_bare_value_still_works_both_ways
    test_status_names_the_input_with_a_high_byte
    test_flip_from_hdmi_goes_home
    test_flip_refuses_an_unrecognised_input
    echo "smoketest_monctl: ${pass} passed, ${fail} failed"
    [[ ${fail} -eq 0 ]]
}

main "$@"
