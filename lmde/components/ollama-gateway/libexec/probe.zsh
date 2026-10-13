#!/bin/zsh -f
# probe.zsh -- the Ollama Gateway's G4 probe (docs/design/OLLAMA-GATEWAY.DESIGN.md,
# G4 and Key Decisions Q7; tds-utils Issue#460). The confinement-mechanism
# seam: the launcher gates every start of the external ollama on this
# probe, never on the profile text, so a successor to sandbox-exec only has
# to pass it.
#
# The behaviors it proves are a TABLE, sandbox/ollama-gateway.probe.tsv,
# one row per property with an expectation per mode. Adding a property to
# the seam is adding a row; a profile change the table does not reflect
# fails at the next launch. Two modes, both run by libexec/launch-ollama.zsh
# before every start:
#
#   control   unconfined. Every row's `control` column must hold, so the
#             confined pass can never succeed vacuously (a missing canary,
#             a port nothing could reach, a path that does not exist).
#   confined  under the sandbox profile, with the parameters ollama gets.
#             Every row's `confined` column must hold. A `deny` row passes
#             only on a denial BY THE SANDBOX ("operation not permitted",
#             EPERM), never on a "no such file" or a "connection refused"
#             that would hold without a sandbox.
#
# Expectations: deny (EPERM observed), permit (anything but EPERM), allow
# (the operation succeeded), skip. Verbs: read, list, write, exec, connect,
# listen, mach-lookup, keychain-framework, keychain-cli (the table's header
# has the grammar). The keychain and mach rows observe the daemon's
# refusal rather than an EPERM: the control pass proves the lookup
# succeeds unconfined, so a refusal confined is the sandbox's.
#
# Usage:
#   probe.zsh control|confined
#       --canary-file <path>        file under $HOME, outside both trees
#       --keychain-service <name>   the non-secret canary keychain item
#                                   (found by attributes; never read)
#       [--keychain <path>]         a keychain file (tests); default: the
#                                   user's keychain search list
#       --store <dir>               the model store (confined: read-only)
#       --guard-dir <dir>           the launcher's code dir (confined:
#                                   unwritable, so a compromised engine
#                                   cannot rewrite what runs it next)
#       [--gateway-home <dir>]      ollama's HOME (confined: writable);
#                                   default: beside the guard dir
#       [--user-tmpdir <dir>]       the user's DARWIN_USER_TEMP_DIR
#                                   (confined: unreadable); default: from
#                                   getconf
#       [--deny-port <port>]        the everyday ollama's port (11434)
#       [--proxy-port <port>]       the deadline proxy's port (11436)
#       [--ollama-port <port>]      the engine's own listen port (11435)
#       [--spec <tsv>]              the table; default: beside the profile
#
# Prints one line per row, "ok <check>" or "FAIL <check>: <why>", and
# exits 0 only when every row held (1 on a failed row, 2 on usage). It
# never prints a canary's value, and it never reads the keychain canary's
# secret at all (tds-utils Issue#441): Keychain reachability is proven by
# ATTRIBUTE-only lookups, which evaluate neither the item's access list
# nor its partition list, so they need no authorization and cannot
# prompt. Belt and braces, it never raises a Keychain dialog (G7): the
# Security framework checker runs with Keychain UI switched off, and
# /usr/bin/security -- which has no such switch -- is tried only once
# that checker has just found the canary without one, or (confined)
# found the keychain unreachable.

set -euo pipefail
zmodload zsh/net/tcp

# --- Constants ---

readonly SCRIPT_DIR="${0:A:h}"
readonly KEYCHAIN_PROBE="${SCRIPT_DIR}/keychain-probe.py"
readonly PYTHON="/usr/bin/python3"
readonly SECURITY_CLI="/usr/bin/security"
readonly EPERM_TEXT="operation not permitted"
# keychain-probe.py's exit codes: found, and refused for want of a dialog
# (it switches Keychain UI off, so it is refused, never prompted).
readonly FRAMEWORK_FOUND=0
readonly FRAMEWORK_NEEDS_DIALOG=3
# Not one of the checker's codes: it printed no status line at all.
readonly FRAMEWORK_NOT_RUN=99
readonly -a EXPECTATIONS=(deny permit allow skip)
readonly -a VERBS=(read list write exec connect listen mach-lookup keychain-framework keychain-cli)
readonly MACH_PROBE="${SCRIPT_DIR}/mach-probe.py"
readonly MACH_NO_SUCH_SERVICE=3

# --- Flags / config (set by parse_args) ---

typeset MODE="" CANARY_FILE="" KEYCHAIN_SERVICE="" KEYCHAIN="" STORE="" GUARD_DIR=""
typeset GATEWAY_HOME="" USER_TMPDIR="" SPEC=""
typeset DENY_PORT="11434" PROXY_PORT="11436" OLLAMA_PORT="11435" MODE_TAG=""
integer FAILURES=0
# The framework row's answer, so the CLI row can refuse to try when a
# dialog could follow (the table orders the two rows).
integer FRAMEWORK_RESULT=-1

# --- Predicates ---

# is_sandbox_denial <error text> -- did the sandbox (EPERM) refuse this?
is_sandbox_denial() {
    [[ "${1:l}" == *"${EPERM_TEXT}"* ]]
}

is_expectation() { (( ${EXPECTATIONS[(Ie)$1]} )); }
is_verb() { (( ${VERBS[(Ie)$1]} )); }

# --- Pure helpers ---

usage() {
    print -u2 -- "usage: probe.zsh control|confined --canary-file <path> --keychain-service <name> [--keychain <path>] --store <dir> --guard-dir <dir> [--gateway-home <dir>] [--user-tmpdir <dir>] [--deny-port <port>] [--proxy-port <port>] [--spec <tsv>]"
}

# expand <target> -- the probe's parameters substituted; nothing else.
expand() {
    local t="$1"
    t="${t//\$CANARY_FILE/${CANARY_FILE}}"
    t="${t//\$KEYCHAIN_SERVICE/${KEYCHAIN_SERVICE}}"
    t="${t//\$STORE/${STORE}}"
    t="${t//\$GUARD_DIR/${GUARD_DIR}}"
    t="${t//\$GATEWAY_HOME/${GATEWAY_HOME}}"
    t="${t//\$USER_TMPDIR/${USER_TMPDIR}}"
    t="${t//\$DENY_PORT/${DENY_PORT}}"
    t="${t//\$PROXY_PORT/${PROXY_PORT}}"
    t="${t//\$OLLAMA_PORT/${OLLAMA_PORT}}"
    t="${t//\$UID/${UID}}"
    print -r -- "${t}"
}

# --- Reporting ---

# Lines name the row; the control pass says so, since a row named for the
# confined property ("...-denied") reads as its opposite unconfined.
pass() { print -r -- "ok $1${MODE_TAG}"; }
flunk() { print -r -- "FAIL $1${MODE_TAG}: $2"; FAILURES+=1; }

# --- Effectful helpers: one attempt each ---
#
# Each prints an outcome word, then any error text: "allowed", "denied"
# (a sandbox denial) or "other" (failed for another reason).

classify() {
    local rc="$1" err="$2"
    if (( rc == 0 )); then print -r -- "allowed"
    elif is_sandbox_denial "${err}"; then print -r -- "denied"
    else print -r -- "other"
    fi
    [[ -n "${err}" ]] && print -r -- "${err}"
    return 0
}

attempt_read() {
    local out rc=0
    out="$( { : < "$1"; } 2>&1 )" || rc=$?
    classify "${rc}" "${out}"
}

# attempt_list <dir> -- open the directory for listing. No -d test first:
# under the profile even stat of a denied path is refused, and the denial
# has to be observed as EPERM text, not as a silent false.
attempt_list() {
    local out rc=0
    out="$( { ls -- "$1" >/dev/null; } 2>&1 )" || rc=$?
    classify "${rc}" "${out}"
}

attempt_write() {
    local target="$1/.ollama-gateway-probe.$$" out rc=0
    out="$( { : > "${target}"; } 2>&1 )" || rc=$?
    (( rc == 0 )) && rm -f -- "${target}"
    classify "${rc}" "${out}"
}

# attempt_exec <path> [args] -- run the command; a sandbox refusal to exec
# or to reach what it needs surfaces as EPERM in its output or as exit 126.
attempt_exec() {
    local out rc=0
    out="$( "$@" 2>&1 )" || rc=$?
    if (( rc == 126 )) && [[ -z "${out}" ]]; then out="${EPERM_TEXT}"; fi
    classify "${rc}" "${out}"
}

# attempt_connect <host:port> -- TCP connect; closes on success.
attempt_connect() {
    local host="${1%:*}" port="${1##*:}" out rc=0
    out="$( { ztcp "${host}" "${port}" && ztcp -c "${REPLY}"; } 2>&1 )" || rc=$?
    classify "${rc}" "${out}"
}

# attempt_listen <host:port> -- bind and listen; closes on success. A port
# in use is "other" (EADDRINUSE), never a sandbox denial.
attempt_listen() {
    local port="${1##*:}" out rc=0
    out="$( { ztcp -l "${port}" && ztcp -c "${REPLY}"; } 2>&1 )" || rc=$?
    classify "${rc}" "${out}"
}

# attempt_mach_lookup <service> -- ask the bootstrap server for the
# service from a binary the profile does not deny by path (python), so
# the mach-service denial itself is observed. A refusal is reported as a
# sandbox denial; an unknown service is "other".
attempt_mach_lookup() {
    local out rc=0
    out="$("${PYTHON}" "${MACH_PROBE}" "$1" 2>&1)" || rc=$?
    if [[ "${out}" != *"mach-probe: status"* ]]; then
        print -r -- "other"; print -r -- "the mach checker did not run: ${out}"
    elif (( rc == 0 )); then print -r -- "allowed"
    elif (( rc == MACH_NO_SUCH_SERVICE )); then print -r -- "other"; print -r -- "no such service (${out})"
    else print -r -- "denied"; print -r -- "${out}"
    fi
    return 0
}

# keychain_cli_finds -- does /usr/bin/security find the canary item? No -w
# and no -g: it prints attributes only, so the secret is never fetched and
# the item's access list is never evaluated. Output is discarded.
keychain_cli_finds() {
    local -a args=(find-generic-password -s "$1")
    [[ -n "${KEYCHAIN}" ]] && args+=("${KEYCHAIN}")
    "${SECURITY_CLI}" "${args[@]}" >/dev/null 2>&1
}

# keychain_framework_attempt -- ask the Security framework, from a binary
# other than /usr/bin/security and with Keychain UI off, to find the canary
# item (attributes only). Returns keychain-probe.py's exit code, or
# FRAMEWORK_NOT_RUN when the checker never reported a status: a checker
# the profile keeps from running proves nothing, in either direction.
keychain_framework_attempt() {
    local -a args=("${KEYCHAIN_PROBE}" "$1")
    [[ -n "${KEYCHAIN}" ]] && args+=("${KEYCHAIN}")
    local out rc=0
    out="$("${PYTHON}" "${args[@]}" 2>&1)" || rc=$?
    [[ "${out}" == *"keychain-probe: status"* ]] || return "${FRAMEWORK_NOT_RUN}"
    return "${rc}"
}

# --- Row judges ---

# judge <check> <expectation> <outcome> <why> -- one row's verdict from
# the attempt's outcome word.
judge() {
    local check="$1" want="$2" got="$3" why="$4"
    case "${want}" in
        deny)
            case "${got}" in
                denied) pass "${check}" ;;
                allowed) flunk "${check}" "not denied: the operation succeeded" ;;
                *) flunk "${check}" "not a sandbox denial: ${why:-failed for another reason}" ;;
            esac ;;
        permit)
            case "${got}" in
                denied) flunk "${check}" "refused by the sandbox: ${why}" ;;
                *) pass "${check}" ;;
            esac ;;
        allow)
            case "${got}" in
                allowed) pass "${check}" ;;
                *) flunk "${check}" "did not succeed: ${why:-denied}" ;;
            esac ;;
        skip) ;;
    esac
}

# run_attempt <verb> <target...> -- outcome word on the first line, error
# text after it.
run_attempt() {
    local verb="$1"; shift
    case "${verb}" in
        read) attempt_read "$1" ;;
        list) attempt_list "$1" ;;
        write) attempt_write "$1" ;;
        exec) attempt_exec "$@" ;;
        connect) attempt_connect "$1" ;;
        listen) attempt_listen "$1" ;;
        mach-lookup) attempt_mach_lookup "$1" ;;
    esac
}

# The keychain rows carry their own logic: the framework first, with UI
# off; a refusal for want of a dialog counts as "the daemon answered"
# (reachable), and the CLI is then never tried, since it could prompt.
judge_keychain_framework() {
    local check="$1" want="$2" service="$3"
    integer rc=0
    keychain_framework_attempt "${service}" || rc=$?
    FRAMEWORK_RESULT=rc
    if (( rc == FRAMEWORK_NOT_RUN )); then
        flunk "${check}" "the Security framework checker (${PYTHON} ${KEYCHAIN_PROBE:t}) did not run, so nothing was proven; allow what it needs or fix it"
        return 0
    fi
    case "${want}" in
        deny)
            case "${rc}" in
                "${FRAMEWORK_FOUND}") flunk "${check}" "the keychain canary is reachable via the Security framework" ;;
                "${FRAMEWORK_NEEDS_DIALOG}") flunk "${check}" "the keychain daemon answered from inside the sandbox (it refused only for want of a dialog)" ;;
                *) pass "${check}" ;;
            esac ;;
        allow|permit)
            case "${rc}" in
                "${FRAMEWORK_FOUND}") pass "${check}" ;;
                "${FRAMEWORK_NEEDS_DIALOG}")
                    flunk "${check}" "keychain item ${service} could be looked up only through a Keychain dialog, which an attribute lookup should never need; the probe never raises one: unlock the keychain, or re-run setup.sh to recreate the canary" ;;
                *) flunk "${check}" "keychain item ${service} is not found via the Security framework (${PYTHON}); run setup.sh" ;;
            esac ;;
        skip) ;;
    esac
}

judge_keychain_cli() {
    local check="$1" want="$2" service="$3"
    if (( FRAMEWORK_RESULT == FRAMEWORK_NEEDS_DIALOG )); then
        flunk "${check}" "not attempted: the keychain wants a dialog, which ${SECURITY_CLI} cannot be kept from raising"
        return 0
    fi
    if [[ "${want}" != deny ]] && (( FRAMEWORK_RESULT != FRAMEWORK_FOUND )); then
        flunk "${check}" "not attempted: the Security framework did not find ${service} without a dialog, and ${SECURITY_CLI} cannot be kept from raising one"
        return 0
    fi
    local found=0
    keychain_cli_finds "${service}" && found=1
    case "${want}" in
        deny)
            if (( found )); then flunk "${check}" "the keychain canary is reachable via ${SECURITY_CLI}"
            else pass "${check}"; fi ;;
        allow|permit)
            if (( found )); then pass "${check}"
            else flunk "${check}" "keychain item ${service} is not found via ${SECURITY_CLI}; run setup.sh"; fi ;;
        skip) ;;
    esac
}

# --- Flow: the table ---

# run_row <check> <confined> <control> <verb> <target...>
run_row() {
    local check="$1" want verb="$4"
    case "${MODE}" in
        confined) want="$2" ;;
        control) want="$3" ;;
    esac
    shift 4
    local -a target=("${(@f)$(for t in "$@"; do expand "${t}"; done)}")
    is_expectation "${want}" || { flunk "${check}" "unknown expectation '${want}' in the spec"; return 0; }
    is_verb "${verb}" || { flunk "${check}" "unknown verb '${verb}' in the spec"; return 0; }
    [[ "${want}" == skip ]] && return 0
    case "${verb}" in
        keychain-framework) judge_keychain_framework "${check}" "${want}" "${target[1]}" ;;
        keychain-cli) judge_keychain_cli "${check}" "${want}" "${target[1]}" ;;
        *)
            local -a result
            result=("${(@f)$(run_attempt "${verb}" "${target[@]}")}")
            judge "${check}" "${want}" "${result[1]}" "${(j: :)result[2,-1]}" ;;
    esac
}

run_spec() {
    local line
    integer rows=0
    [[ -f "${SPEC}" ]] || { print -u2 -r -- "probe: spec not found: ${SPEC}"; exit 2; }
    while IFS= read -r line || [[ -n "${line}" ]]; do
        [[ -z "${line}" || "${line}" == \#* ]] && continue
        local -a f=("${(@s:	:)line}")
        (( ${#f} >= 5 )) || { flunk "spec" "malformed row: ${line}"; continue; }
        rows+=1
        run_row "${f[1]}" "${f[2]}" "${f[3]}" "${f[4]}" "${(@s: :)f[5]}"
    done < "${SPEC}"
    (( rows > 0 )) || flunk "spec" "no rows in ${SPEC}"
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
            --gateway-home) GATEWAY_HOME="$2" ;;
            --user-tmpdir) USER_TMPDIR="$2" ;;
            --deny-port) DENY_PORT="$2" ;;
            --proxy-port) PROXY_PORT="$2" ;;
            --ollama-port) OLLAMA_PORT="$2" ;;
            --spec) SPEC="$2" ;;
            *) usage; exit 2 ;;
        esac
        shift 2
    done
    [[ -n "${CANARY_FILE}" && -n "${KEYCHAIN_SERVICE}" && -n "${STORE}" && -n "${GUARD_DIR}" ]] \
        || { usage; exit 2; }
    [[ "${MODE}" == control || "${MODE}" == confined ]] || { usage; exit 2; }
    [[ "${MODE}" == control ]] && MODE_TAG=" [control]"
    [[ -f "${MACH_PROBE}" ]] || { print -u2 -r -- "probe: mach checker not found: ${MACH_PROBE}"; exit 2; }
    [[ -n "${GATEWAY_HOME}" ]] || GATEWAY_HOME="${GUARD_DIR:h}/home"
    # The launcher passes the user's temp dir; getconf cannot run under the
    # profile (and must not end the probe), so the fallback is the tree
    # every per-user temp dir lives in.
    if [[ -z "${USER_TMPDIR}" ]]; then
        USER_TMPDIR="$(getconf DARWIN_USER_TEMP_DIR 2>/dev/null || true)"
        USER_TMPDIR="${USER_TMPDIR:-/private/var/folders}"
    fi
    USER_TMPDIR="${USER_TMPDIR%/}"
    [[ -n "${SPEC}" ]] || SPEC="${SCRIPT_DIR:h}/sandbox/ollama-gateway.probe.tsv"
}

main() {
    parse_args "$@"
    run_spec
    (( FAILURES == 0 ))
}

main "$@"
