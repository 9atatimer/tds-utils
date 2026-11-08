#!/bin/zsh -f
# seed-gateway-key.zsh -- copy omp's AI Gateway key from 1Password into the
# macOS login Keychain, where clai.d/omp/pre/30-cf-workers-ai points omp.
# Once seeded, an omp launch reads the key with `security` and never asks
# 1Password. A HUMAN runs this, once per laptop and after every rotation of
# the key. An agent never does.
#
# Usage: seed-gateway-key.zsh [<op-reference>]
#
#   <op-reference>  the key's op:// reference. Without it, the one 1Password
#                   item tagged KEY_TAG gives op://<vault id>/<item id>/credential.
#                   This repo is public: it names the tag, never the item.
#
# Then it runs 30-cf-workers-ai with CLAI_OMP_REFRESH=1, so models.yml
# points at the Keychain now and its routing is read while you are here.
#
# The key is read with `op read`, written with `security -i` from stdin --
# so it is never on a command line -- and never printed.
#
# The item: service tds.omp.cf-gateway-key, account omp, readable without a
# prompt only by /usr/bin/security.
#
# Environment (tests only): CLAI_OMP_KEYCHAIN, a keychain file to write
# instead of the default (login) keychain; CLAI_OMP_SEED_NO_HOOK=1 skips the
# hook run.

set -euo pipefail

# --- Constants ---

readonly KEY_TAG="omp-ai-gateway-key"
readonly KEY_SERVICE="tds.omp.cf-gateway-key"
readonly KEY_ACCOUNT="omp"
readonly HOOK="${0:A:h}/pre/30-cf-workers-ai"

# --- Reporting ---

die() { print -u2 -r -- "seed-gateway-key: $*"; exit 1; }
say() { print -r -- "seed-gateway-key: $*"; }

# --- Predicates ---

is_op_reference() { [[ "$1" =~ '^op://[^/]+/[^/]+/.+' ]]; }
is_key_shaped() { [[ -n "$1" && "$1" =~ '^[A-Za-z0-9+/=_.-]+$' ]]; }

# --- Preconditions ---

require_human_session() {
    [[ -t 0 ]] || die "run this yourself, in a terminal: seeding is an interactive op session"
    [[ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]] \
        || die "OP_SERVICE_ACCOUNT_TOKEN is set; unset it -- seeding is a human op session"
    whence -p op >/dev/null || die "op (1Password CLI) not found on PATH"
    whence -p security >/dev/null || die "security not found on PATH"
    whence -p jq >/dev/null || die "jq not found on PATH"
}

# --- Actions ---

# The reference of the one item tagged KEY_TAG.
reference_by_tag() {
    local items count
    items="$(op item list --tags "${KEY_TAG}" --format json)" || die "op item list failed (is 1Password unlocked?)"
    count="$(jq 'length' <<<"${items}")"
    [[ "${count}" == 1 ]] || die "${count} 1Password items carry the tag ${KEY_TAG}; want exactly 1"
    jq -r '.[0] | "op://\(.vault.id)/\(.id)/credential"' <<<"${items}"
}

# write_key <key> -- add or update the keychain item. The command line goes
# to `security -i` on stdin, so the key never lands in argv.
write_key() {
    local -a target=()
    [[ -n "${CLAI_OMP_KEYCHAIN:-}" ]] && target=("${CLAI_OMP_KEYCHAIN}")
    print -r -- "add-generic-password -U -s ${KEY_SERVICE} -a ${KEY_ACCOUNT} -T /usr/bin/security -w \"$1\" ${target[*]}" \
        | security -i >/dev/null
    security find-generic-password -s "${KEY_SERVICE}" -a "${KEY_ACCOUNT}" "${target[@]}" >/dev/null 2>&1 \
        || die "the keychain item was not written (is the keychain unlocked?)"
}

# --- Main ---

main() {
    (( $# <= 1 )) || die "usage: seed-gateway-key.zsh [<op-reference>]"
    require_human_session
    local ref="${1:-}" key
    if [[ -n "${ref}" ]]; then
        is_op_reference "${ref}" || die "not an op:// reference: expected op://<vault>/<item>/<field>"
    else
        ref="$(reference_by_tag)"
    fi

    say "reading omp's gateway key from 1Password (approve the desktop app prompt)..."
    key="$(op read --no-newline "${ref}")" || die "op read failed"
    is_key_shaped "${key}" || { key=""; die "the value is not a key; nothing written"; }

    write_key "${key}"
    key=""
    say "the key is in the keychain (service ${KEY_SERVICE})."

    [[ "${CLAI_OMP_SEED_NO_HOOK:-0}" == 1 ]] && return 0
    CLAI_OMP_REFRESH=1 "${HOOK}"
    say "omp reads the key from the keychain from its next launch."
}

main "$@"
