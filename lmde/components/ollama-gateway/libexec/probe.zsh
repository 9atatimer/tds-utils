#!/bin/zsh -f
# probe.zsh -- the Ollama Gateway's G4 probe (docs/design/OLLAMA-GATEWAY.DESIGN.md,
# G4 and Key Decisions Q7). The confinement-mechanism seam: the launcher
# gates every start of the external ollama on this probe, never on the
# profile text, so a successor to sandbox-exec only has to pass it.
#
# Two modes, both run by libexec/launch-ollama.zsh before every start:
#
#   control   unconfined. Proves the canaries are reachable, so the
#             confined pass can never succeed vacuously (a missing canary
#             is a failure here, not a pass there).
#   confined  under the sandbox profile, with the parameters ollama gets.
#             Every check must observe a denial BY THE SANDBOX: an
#             "operation not permitted" (EPERM), never a "no such file" or
#             a "connection refused" that would hold without a sandbox.
#
# Usage:
#   probe.zsh control|confined
#       --canary-file <path>        file under $HOME, outside both trees
#       --keychain-service <name>   the non-secret canary keychain item
#       [--keychain <path>]         a keychain file (tests); default: the
#                                   user's keychain search list
#       --store <dir>               the model store (confined: read-only)
#       --guard-dir <dir>           the launcher's code dir (confined:
#                                   unwritable, so a compromised engine
#                                   cannot rewrite what runs it next)
#       [--deny-port <port>]        the everyday ollama's port (11434)
#
# Prints one line per check, "ok <check>" or "FAIL <check>: <why>", and
# exits 0 only when every check passed (1 on a failed check, 2 on usage).
# It never prints a canary's value, and it never raises a Keychain dialog
# (tds-utils Issue#441, G7): the Security framework checker runs with
# Keychain UI switched off, and /usr/bin/security -- which has no such
# switch -- is tried only once that checker has just proved the canary
# readable without one, or (confined) the keychain unreachable.

set -euo pipefail
zmodload zsh/net/tcp

# --- Constants ---

readonly SCRIPT_DIR="${0:A:h}"
readonly KEYCHAIN_PROBE="${SCRIPT_DIR}/keychain-probe.py"
readonly PYTHON="/usr/bin/python3"
readonly SECURITY_CLI="/usr/bin/security"
readonly EPERM_TEXT="operation not permitted"
# keychain-probe.py's exit codes: retrieved, and refused for want of a
# dialog (it switches Keychain UI off, so it is refused, never prompted).
readonly FRAMEWORK_RETRIEVED=0
readonly FRAMEWORK_NEEDS_DIALOG=3

# --- Flags / config (set by parse_args) ---

typeset MODE="" CANARY_FILE="" KEYCHAIN_SERVICE="" KEYCHAIN="" STORE="" GUARD_DIR=""
typeset DENY_PORT="11434"
integer FAILURES=0

# --- Predicates ---

# is_sandbox_denial <error text> -- did the sandbox (EPERM) refuse this?
is_sandbox_denial() {
    [[ "${1:l}" == *"${EPERM_TEXT}"* ]]
}

# --- Pure helpers ---

usage() {
    print -u2 -- "usage: probe.zsh control|confined --canary-file <path> --keychain-service <name> [--keychain <path>] --store <dir> --guard-dir <dir> [--deny-port <port>]"
}

# --- Reporting ---

pass() { print -r -- "ok $1"; }
flunk() { print -r -- "FAIL $1: $2"; FAILURES+=1; }

# --- Effectful helpers: one attempt each, result as text ---

# read_attempt <path> -- open the file for reading; print the error text, if
# any. Returns 0 when the read succeeded.
read_attempt() {
    local out
    if out="$( { : < "$1"; } 2>&1 )"; then
        return 0
    fi
    print -r -- "${out}"
    return 1
}

# write_attempt <dir> -- create (then remove) a file in <dir>; print the
# error text, if any. Returns 0 when the write succeeded.
write_attempt() {
    local target="$1/.ollama-gateway-probe.$$" out
    if out="$( { : > "${target}"; } 2>&1 )"; then
        rm -f -- "${target}"
        return 0
    fi
    print -r -- "${out}"
    return 1
}

# keychain_cli_retrieves -- does /usr/bin/security hand over the canary's
# secret? Output is discarded: the value is never printed.
keychain_cli_retrieves() {
    local -a args=(find-generic-password -s "${KEYCHAIN_SERVICE}" -w)
    [[ -n "${KEYCHAIN}" ]] && args+=("${KEYCHAIN}")
    "${SECURITY_CLI}" "${args[@]}" >/dev/null 2>&1
}

# keychain_framework_attempt -- ask the Security framework, from a binary
# other than /usr/bin/security and with Keychain UI off, for the canary's
# secret. Returns keychain-probe.py's exit code (FRAMEWORK_*; any other
# non-zero is "not retrieved").
keychain_framework_attempt() {
    local -a args=("${KEYCHAIN_PROBE}" "${KEYCHAIN_SERVICE}")
    [[ -n "${KEYCHAIN}" ]] && args+=("${KEYCHAIN}")
    "${PYTHON}" "${args[@]}" >/dev/null 2>&1
}

# connect_attempt <port> -- TCP connect to 127.0.0.1:<port>; print the error
# text, if any. Returns 0 when the connection was made (and closes it).
connect_attempt() {
    local out
    if out="$( { ztcp 127.0.0.1 "$1" && ztcp -c "${REPLY}"; } 2>&1 )"; then
        return 0
    fi
    print -r -- "${out}"
    return 1
}

# --- Flow: control (unconfined) ---

run_control() {
    local err
    if err="$(read_attempt "${CANARY_FILE}")"; then
        pass canary-file-readable
    else
        flunk canary-file-readable "the file canary ${CANARY_FILE} is not readable unconfined (${err}); run setup.sh"
    fi
    integer framework=0
    keychain_framework_attempt || framework=$?
    case "${framework}" in
        "${FRAMEWORK_RETRIEVED}") pass keychain-framework-reachable ;;
        "${FRAMEWORK_NEEDS_DIALOG}")
            flunk keychain-framework-reachable "keychain item ${KEYCHAIN_SERVICE} is readable unconfined only through a Keychain dialog (the keychain is locked, or the item's access list does not admit ${PYTHON}); the probe never raises one: unlock the keychain, or re-run setup.sh to recreate the canary" ;;
        *)
            flunk keychain-framework-reachable "keychain item ${KEYCHAIN_SERVICE} is not retrievable unconfined via the Security framework (${PYTHON}); run setup.sh" ;;
    esac
    if (( framework != FRAMEWORK_RETRIEVED )); then
        flunk keychain-cli-reachable "not attempted: the Security framework did not prove ${KEYCHAIN_SERVICE} readable without a dialog, and ${SECURITY_CLI} cannot be kept from raising one"
    elif keychain_cli_retrieves; then
        pass keychain-cli-reachable
    else
        flunk keychain-cli-reachable "keychain item ${KEYCHAIN_SERVICE} is not retrievable unconfined via ${SECURITY_CLI}; run setup.sh (or unlock the keychain)"
    fi
}

# --- Flow: confined (under the profile) ---

check_canary_file() {
    local err
    if err="$(read_attempt "${CANARY_FILE}")"; then
        flunk canary-file-unreadable "the file canary under \$HOME is readable"
    elif is_sandbox_denial "${err}"; then
        pass canary-file-unreadable
    else
        flunk canary-file-unreadable "not a sandbox denial: ${err}"
    fi
}

# check_keychain -- the framework first, with Keychain UI off. A refusal for
# want of a dialog means the keychain daemon answered from inside the
# sandbox: a hole, and a keychain the CLI could prompt for, so the CLI is
# not tried. Otherwise the CLI cannot prompt: either the canary was just
# read without a dialog, or the daemon is unreachable to it as well.
check_keychain() {
    integer framework=0
    keychain_framework_attempt || framework=$?
    case "${framework}" in
        "${FRAMEWORK_RETRIEVED}")
            flunk keychain-framework-denied "the keychain canary is retrievable via the Security framework" ;;
        "${FRAMEWORK_NEEDS_DIALOG}")
            flunk keychain-framework-denied "the keychain daemon answered from inside the sandbox (it refused only for want of a dialog)" ;;
        *) pass keychain-framework-denied ;;
    esac
    if (( framework == FRAMEWORK_NEEDS_DIALOG )); then
        flunk keychain-cli-denied "not attempted: the keychain is reachable and wants a dialog, which ${SECURITY_CLI} cannot be kept from raising"
    elif keychain_cli_retrieves; then
        flunk keychain-cli-denied "the keychain canary is retrievable via ${SECURITY_CLI}"
    else
        pass keychain-cli-denied
    fi
}

check_loopback() {
    local err
    if err="$(connect_attempt "${DENY_PORT}")"; then
        flunk loopback-everyday-denied "connected to 127.0.0.1:${DENY_PORT}"
    elif is_sandbox_denial "${err}"; then
        pass loopback-everyday-denied
    else
        flunk loopback-everyday-denied "127.0.0.1:${DENY_PORT} not denied by the sandbox (${err})"
    fi
}

# check_unwritable <check> <dir> -- a write into <dir> must be a sandbox denial.
check_unwritable() {
    local check="$1" dir="$2" err
    if err="$(write_attempt "${dir}")"; then
        flunk "${check}" "wrote into ${dir}"
    elif is_sandbox_denial "${err}"; then
        pass "${check}"
    else
        flunk "${check}" "not a sandbox denial: ${err}"
    fi
}

check_store_readable() {
    if [[ -d "${STORE}" ]] && ls -- "${STORE}" >/dev/null 2>&1; then
        pass store-readable
    else
        flunk store-readable "the model store ${STORE} is not readable; ollama could serve nothing"
    fi
}

run_confined() {
    check_canary_file
    check_keychain
    check_loopback
    check_unwritable store-write-denied "${STORE}"
    check_unwritable guard-write-denied "${GUARD_DIR}"
    check_store_readable
}

# --- Entry point ---

parse_args() {
    (( $# >= 1 )) || { usage; exit 2; }
    MODE="$1"
    shift
    while (( $# > 0 )); do
        (( $# >= 2 )) || { usage; exit 2; }
        case "$1" in
            --canary-file) CANARY_FILE="$2" ;;
            --keychain-service) KEYCHAIN_SERVICE="$2" ;;
            --keychain) KEYCHAIN="$2" ;;
            --store) STORE="$2" ;;
            --guard-dir) GUARD_DIR="$2" ;;
            --deny-port) DENY_PORT="$2" ;;
            *) usage; exit 2 ;;
        esac
        shift 2
    done
    [[ -n "${CANARY_FILE}" && -n "${KEYCHAIN_SERVICE}" && -n "${STORE}" && -n "${GUARD_DIR}" ]] \
        || { usage; exit 2; }
}

main() {
    parse_args "$@"
    case "${MODE}" in
        control) run_control ;;
        confined) run_confined ;;
        *) usage; exit 2 ;;
    esac
    (( FAILURES == 0 ))
}

main "$@"
