#!/bin/zsh -f
# seed-tunnel-token.zsh -- copy the Ollama Gateway tunnel's run token from
# 1Password into the macOS login Keychain, where the connector launcher
# reads it (docs/design/OLLAMA-GATEWAY.DESIGN.md, Connector daemon; Key
# Decisions Q9). A HUMAN runs this, once per laptop and after every token
# rotation. An agent never does.
#
# Usage: seed-tunnel-token.zsh <op-reference>
#
#   <op-reference>  the run token's op:// reference. It is named in the
#                   tds-internal edge record, not here: this repo is public.
#
# Authentication is an interactive human `op` session (the CLI unlocked
# through the 1Password desktop app), never a service account: the token's
# vault has zero service-account grants. Nothing of 1Password persists
# afterward. The token is read with `op read`, written with `security -i`
# from stdin -- so it is never on a command line -- and never printed.
#
# The item: service lmde.ollama-gateway.tunnel-token, account
# ollama-gateway, readable without a prompt only by /usr/bin/security.
#
# Environment (tests only): OLLAMA_GATEWAY_KEYCHAIN, a keychain file to
# write instead of the default (login) keychain.

set -euo pipefail

# --- Constants ---

readonly TOKEN_SERVICE="lmde.ollama-gateway.tunnel-token"
readonly TOKEN_ACCOUNT="ollama-gateway"
readonly CONNECTOR_LABEL="com.tds.lmde.ollama-gateway.connector"

# --- Reporting ---

die() { print -u2 -r -- "seed-tunnel-token: $*"; exit 1; }
say() { print -r -- "seed-tunnel-token: $*"; }

# --- Predicates ---

is_op_reference() { [[ "$1" =~ '^op://[^/]+/[^/]+/.+' ]]; }
is_token_shaped() { [[ -n "$1" && "$1" =~ '^[A-Za-z0-9+/=_-]+$' ]]; }

# --- Preconditions ---

require_human_session() {
    [[ -t 0 ]] || die "run this yourself, in a terminal: seeding is an interactive human op session (Q9)"
    [[ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]] \
        || die "OP_SERVICE_ACCOUNT_TOKEN is set; unset it -- the run token's vault grants no service account, seeding is a human op session (Q9)"
    [[ -z "${OP_CONNECT_TOKEN:-}" ]] \
        || die "OP_CONNECT_TOKEN is set; unset it -- seeding is a human op session (Q9)"
    whence -p op >/dev/null || die "op (1Password CLI) not found on PATH"
    whence -p security >/dev/null || die "security not found on PATH"
}

# --- Flow ---

# write_token <token> -- add or update the keychain item. The command line
# goes to `security -i` on stdin, so the token never lands in argv.
write_token() {
    local -a target=()
    [[ -n "${OLLAMA_GATEWAY_KEYCHAIN:-}" ]] && target=("${OLLAMA_GATEWAY_KEYCHAIN}")
    print -r -- "add-generic-password -U -s ${TOKEN_SERVICE} -a ${TOKEN_ACCOUNT} -T /usr/bin/security -w \"$1\" ${target[*]}" \
        | security -i >/dev/null
    security find-generic-password -s "${TOKEN_SERVICE}" -a "${TOKEN_ACCOUNT}" "${target[@]}" >/dev/null 2>&1 \
        || die "the keychain item was not written (is the keychain unlocked?)"
}

next_steps() {
    cat <<EOF
seed-tunnel-token: the run token is in the keychain (service ${TOKEN_SERVICE}).

  Start the connector (enables it at login, then loads it now):
    launchctl enable gui/\$(id -u)/${CONNECTOR_LABEL}
    launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/${CONNECTOR_LABEL}.plist

  Already loaded? Restart it to pick up a rotated token:
    launchctl kickstart -k gui/\$(id -u)/${CONNECTOR_LABEL}
EOF
}

main() {
    (( $# == 1 )) || die "usage: seed-tunnel-token.zsh <op-reference>"
    local ref="$1" token
    is_op_reference "${ref}" || die "not an op:// reference: expected op://<vault>/<item>/<field>"
    require_human_session

    say "reading the run token from 1Password (approve the desktop app prompt)..."
    token="$(op read --no-newline "${ref}")" || die "op read failed for the given reference"
    is_token_shaped "${token}" || { token=""; die "the value at that reference is not a tunnel run token; nothing written"; }

    write_token "${token}"
    token=""
    next_steps
}

main "$@"
