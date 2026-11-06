#!/usr/bin/env bash
# smoketest_dot_alias.sh -- behavioral smoke test for the functions in
# macos/dot.alias that read machine data from the environment.
#
# Hermetic: the file is sourced under bash (its functions are POSIX enough
# for both shells; the syntax sweep covers the zsh parse), ssh is a fake on
# PATH that records its arguments, and nothing is connected to.
#
# Usage: ./test/smoketest_dot_alias.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
ALIAS_FILE="${REPO_DIR}/macos/dot.alias"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1" condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

cleanup() { [ -n "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT INT TERM HUP

# --- Fixture ---------------------------------------------------------------

install_fakes() {
    mkdir -p "${WORKROOT}/bin"
    printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "${FAKE_LOG:?}"\n' > "${WORKROOT}/bin/ssh"
    chmod +x "${WORKROOT}/bin/ssh"
}

# run_fn [VAR=value ...] -- <function> [args]: source the alias file in a
# child bash with the fakes first on PATH, then call the function.
run_fn() {
    local assigns=()
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do assigns+=("$1"); shift; done
    shift
    RUN_RC=0
    RUN_OUT=$(env -i HOME="${HOME}" PATH="${WORKROOT}/bin:${PATH}" FAKE_LOG="${WORKROOT}/log" \
        "${assigns[@]+"${assigns[@]}"}" bash -c 'source "$1"; shift; "$@"' _ "${ALIAS_FILE}" "$@" \
        2> "${WORKROOT}/stderr") || RUN_RC=$?
    RUN_ERR=$(cat "${WORKROOT}/stderr")
}

# --- Cases -----------------------------------------------------------------

case_bit_tunnel_refuses_when_unset() {
    bold "bit-tunnel with TDS_BIT_TUNNEL_HOST unset: refuses, names the variable, no ssh"; echo
    : > "${WORKROOT}/log"
    run_fn -- bit-tunnel
    assert "exit 1" "[ \"\${RUN_RC}\" -eq 1 ]"
    assert "the message names TDS_BIT_TUNNEL_HOST and the overlay" "printf '%s' \"\${RUN_ERR}\" | grep -q 'TDS_BIT_TUNNEL_HOST' && printf '%s' \"\${RUN_ERR}\" | grep -q 'tds-local'"
    assert "ssh was not called" "[ ! -s '${WORKROOT}/log' ]"
}

case_bit_tunnel_forwards_to_the_configured_host() {
    bold "bit-tunnel with TDS_BIT_TUNNEL_HOST set: forwards 5678 to that host"; echo
    : > "${WORKROOT}/log"
    run_fn TDS_BIT_TUNNEL_HOST=someone@host.example -- bit-tunnel
    assert "exit 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "ssh got the forward and the host from the variable" "grep -qx -- '-L 5678:127.0.0.1:5678 someone@host.example' '${WORKROOT}/log'"
}

case_alias_file_carries_no_host() {
    bold "the alias file carries no user@host literal and no address but loopback"; echo
    assert "no user@host" "! grep -qE '[A-Za-z0-9_-]+@([0-9]|[a-z0-9-]+\.[a-z])' '${ALIAS_FILE}'"
    assert "no address other than 127.0.0.1" "! grep -oE '[0-9]{1,3}(\.[0-9]{1,3}){3}' '${ALIAS_FILE}' | grep -qv '^127\.0\.0\.1$'"
}

# --- Main ------------------------------------------------------------------

main() {
    WORKROOT=$(mktemp -d)
    install_fakes
    case_bit_tunnel_refuses_when_unset
    case_bit_tunnel_forwards_to_the_configured_host
    case_alias_file_carries_no_host
    echo
    echo "ran ${TESTS_RUN}, passed ${TESTS_PASSED}, failed ${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
