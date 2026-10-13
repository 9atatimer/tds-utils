#!/bin/zsh -f
# launch-connector.zsh -- run the Ollama Gateway's connector: cloudflared
# holding the gateway's remotely managed tunnel open
# (docs/design/OLLAMA-GATEWAY.DESIGN.md: Connector daemon; Key Decisions
# Transport, Connector run token on the laptop).
#
# Run by launchd (com.tds.lmde.ollama-gateway.connector), which restarts it
# after a non-zero exit. The run token is read from the login Keychain at
# launch -- seeded once by a human with seed-tunnel-token.zsh -- and handed
# to cloudflared through a pipe (--token-file /dev/fd/N). It never appears
# on a command line, in the environment, in the plist or in a file.
#
# No token, no start: a missing or blank token exits 78 naming the item.
# cloudflared runs with HOME and --config pointed into the gateway tree, so
# it can never fall back to ~/.cloudflared and another tunnel's credentials.
#
# Environment (optional; tests only):
#   OLLAMA_GATEWAY_TREE      gateway config tree (default ~/.local/share/ollama-gateway)
#   OLLAMA_GATEWAY_KEYCHAIN  keychain file holding the token (default: the
#                            user's search list, i.e. the login keychain)
#
# zsh: macOS-only (Keychain, launchd), per AGENT.md.

set -euo pipefail

# --- Constants ---

readonly SECURITY_CLI="/usr/bin/security"
readonly TOKEN_SERVICE="lmde.ollama-gateway.tunnel-token"
readonly TOKEN_ACCOUNT="ollama-gateway"
readonly EX_CONFIG=78
readonly CHILD_PATH="/usr/bin:/bin:/usr/sbin:/sbin"

# --- Reporting ---

log() { print -r -- "launch-connector: $*"; }
die() { print -u2 -r -- "launch-connector: $*"; exit "${EX_CONFIG}"; }

# --- Predicates ---

# is_token_shaped <token> -- non-blank, one line, run-token alphabet only.
is_token_shaped() {
    [[ -n "$1" && "$1" =~ '^[A-Za-z0-9+/=_-]+$' ]]
}

# --- Effectful helpers ---

# read_token -- print the run token from the keychain; fails when absent.
read_token() {
    local -a args=(find-generic-password -s "${TOKEN_SERVICE}" -a "${TOKEN_ACCOUNT}" -w)
    [[ -n "${OLLAMA_GATEWAY_KEYCHAIN:-}" ]] && args+=("${OLLAMA_GATEWAY_KEYCHAIN}")
    "${SECURITY_CLI}" "${args[@]}" 2>/dev/null
}

# --- Flow ---

main() {
    (( $# == 0 )) || die "takes no arguments"
    [[ -n "${HOME:-}" && -d "${HOME}" ]] || die "HOME is not set to a directory"
    local tree="${${OLLAMA_GATEWAY_TREE:-${HOME}/.local/share/ollama-gateway}:A}"
    local connector_home="${tree}/connector"
    local config="${connector_home}/config.yml"
    local cloudflared token

    [[ -f "${config}" ]] || die "connector config not found: ${config}; run setup.sh"
    cloudflared="$(whence -p cloudflared)" || die "cloudflared not found on PATH (${PATH}); brew install cloudflared"

    token="$(read_token)" \
        || die "no tunnel run token in the keychain (item: service ${TOKEN_SERVICE}, account ${TOKEN_ACCOUNT}); a human seeds it with seed-tunnel-token.zsh"
    is_token_shaped "${token}" \
        || die "the keychain item ${TOKEN_SERVICE} does not hold a run token (blank or malformed); re-seed it with seed-tunnel-token.zsh"

    log "starting ${cloudflared} (transport http2, token from the keychain)"
    cd "${connector_home}"
    exec /usr/bin/env -i HOME="${connector_home}" PATH="${CHILD_PATH}" \
        "${cloudflared}" tunnel \
        --config "${config}" \
        --no-autoupdate \
        --protocol http2 \
        --loglevel info \
        run --token-file <(print -r -- "${token}")
}

main "$@"
