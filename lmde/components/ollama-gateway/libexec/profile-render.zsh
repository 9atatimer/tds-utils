#!/bin/zsh -f
# profile-render.zsh -- render the Ollama Gateway's sandbox profile from its
# template (docs/design/OLLAMA-GATEWAY.DESIGN.md, G4; tds-utils Issue#460).
#
# The engine connects to its own runner on a loopback port the kernel
# picks from its ephemeral range (sysctl net.inet.ip.portrange.first/last;
# ollama cannot pin it). SBPL has no port ranges, and an allow for
# "localhost:*" cannot be narrowed by any later deny (measured 2026-10-13),
# so the profile allows each ephemeral port by number: one rule per port,
# read from the kernel where the profile is installed, so a machine with a
# different range gets its own. Everything below the ephemeral range --
# the everyday ollama, the deadline proxy, every other local service on a
# well-known port -- stays unreachable from the engine.
#
# Usage: profile-render.zsh <template.sb.in> <output.sb>
#        [--first <port>] [--last <port>]   (tests; default: sysctl)
#
# Replaces the line `@EPHEMERAL_OUTBOUND@` in the template with one
# outbound allow per ephemeral port (the engine connects to its runner
# there). Bind is not rendered per port: a second block of that size
# exceeds what sandbox_apply accepts (measured 2026-10-13). Writes the
# output atomically. Exit 0 on success, 64 on usage, 78 when the range
# cannot be read or is implausible.

set -euo pipefail

readonly MARKER="@EPHEMERAL_OUTBOUND@"
readonly EX_USAGE=64
readonly EX_CONFIG=78

typeset TEMPLATE="" OUTPUT="" FIRST="" LAST=""

die() { print -u2 -r -- "profile-render: $*"; exit "${2:-${EX_CONFIG}}"; }
usage() { print -u2 -- "usage: profile-render.zsh <template.sb.in> <output.sb> [--first <port>] [--last <port>]"; }

# --- Predicates ---

is_port() { [[ "$1" == <1-65535> ]]; }

# --- Pure helpers ---

# ephemeral_rules <first> <last> -- one outbound allow per ephemeral port,
# on stdout.
ephemeral_rules() {
    integer p="$1" last="$2"
    print -r -- ";; The kernel's ephemeral range on this machine, ${1}-${2}: where ollama's"
    print -r -- ";; runner listens. Rendered by libexec/profile-render.zsh; do not edit."
    while (( p <= last )); do
        print -r -- "(allow network-outbound (remote tcp \"localhost:${p}\"))"
        p+=1
    done
}

# --- Effectful helpers ---

kernel_range() {
    FIRST="${FIRST:-$(sysctl -n net.inet.ip.portrange.first 2>/dev/null)}"
    LAST="${LAST:-$(sysctl -n net.inet.ip.portrange.last 2>/dev/null)}"
    is_port "${FIRST}" && is_port "${LAST}" || die "cannot read the kernel's ephemeral port range (sysctl net.inet.ip.portrange)"
    (( FIRST <= LAST )) || die "implausible ephemeral range ${FIRST}-${LAST}"
    (( FIRST >= 1024 )) || die "ephemeral range starts below 1024 (${FIRST}); refusing to allow well-known ports"
}

render() {
    local tmp="${OUTPUT}.tmp.$$"
    grep -q -x -- "${MARKER}" "${TEMPLATE}" || die "template has no ${MARKER} line: ${TEMPLATE}"
    {
        while IFS= read -r line || [[ -n "${line}" ]]; do
            if [[ "${line}" == "${MARKER}" ]]; then ephemeral_rules "${FIRST}" "${LAST}"
            else print -r -- "${line}"; fi
        done < "${TEMPLATE}"
    } > "${tmp}"
    mv -f -- "${tmp}" "${OUTPUT}"
}

# --- Entry point ---

parse_args() {
    (( $# >= 2 )) || { usage; exit "${EX_USAGE}"; }
    TEMPLATE="$1"; OUTPUT="$2"; shift 2
    while (( $# > 0 )); do
        case "$1" in
            --first) FIRST="$2"; shift 2 ;;
            --last) LAST="$2"; shift 2 ;;
            *) usage; exit "${EX_USAGE}" ;;
        esac
    done
    [[ -f "${TEMPLATE}" ]] || die "template not found: ${TEMPLATE}"

}

main() {
    parse_args "$@"
    kernel_range
    render
    print -r -- "profile-render: ${OUTPUT} (ephemeral loopback ${FIRST}-${LAST})"
}

main "$@"
