#!/usr/bin/env bash
# config.sh -- shared fixtures and assertions for the Ollama Gateway smoke
# tests (lmde/components/ollama-gateway, docs/design/OLLAMA-GATEWAY.DESIGN.md).
#
# Every scenario builds a throwaway "fake home" under a physical temp path
# (sandbox-exec matches resolved paths, so /var -> /private/var matters),
# a throwaway keychain holding only a non-secret canary item, and fakes on
# PATH for anything that would reach launchd, the login keychain or the
# network. Nothing here touches the real $HOME, the login keychain, the
# everyday ollama or a LaunchAgent.
#
# macOS only: sandbox-exec, launchd and the keychain do not exist elsewhere.
# Sourcing is side-effect-free; call fixture_setup from a scenario.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${TEST_DIR}/../.." && pwd)"
COMPONENT_DIR="${REPO_DIR}/lmde/components/ollama-gateway"
PROXY_DIR="${REPO_DIR}/lmde/components/proxy-layer"
PROFILE="${COMPONENT_DIR}/sandbox/ollama-gateway.sb"
PROBE="${COMPONENT_DIR}/libexec/probe.zsh"
LAUNCH_OLLAMA="${COMPONENT_DIR}/libexec/launch-ollama.zsh"
LAUNCH_CONNECTOR="${COMPONENT_DIR}/libexec/launch-connector.zsh"
SEED="${COMPONENT_DIR}/seed-tunnel-token.zsh"
SETUP="${COMPONENT_DIR}/setup.sh"
HEALTHCHECK="${COMPONENT_DIR}/healthcheck.sh"

# The canary keychain item's service name; the value is deliberately not a
# secret. Mirrors the launcher's constant.
CANARY_SERVICE="lmde.ollama-gateway.probe-canary"
KEYCHAIN_PASSWORD="ollama-gateway-test"

WORK=""
FAKE_HOME=""
TREE=""
STORE=""
CANARY_FILE=""
KEYCHAIN=""
FAKE_BIN=""

# --- Platform gate -----------------------------------------------------------

# require_macos -- exit 0 with a skip line on anything but macOS.
require_macos() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        echo "skip: not macOS (sandbox-exec, launchd and the keychain are macOS-only)"
        exit 0
    fi
}

# --- Fixture -----------------------------------------------------------------

fixture_cleanup() {
    if [[ -n "${KEYCHAIN}" && -f "${KEYCHAIN}" ]]; then
        security delete-keychain "${KEYCHAIN}" >/dev/null 2>&1 || true
    fi
    if [[ -n "${WORK}" && -d "${WORK}" ]]; then
        chmod -R u+w "${WORK}" 2>/dev/null || true
        rm -rf "${WORK}"
    fi
    return 0
}

# fixture_setup -- a fake home with the gateway tree, a model store, the file
# canary outside both, and a throwaway keychain holding the canary item.
fixture_setup() {
    WORK="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/ollama-gateway-test.XXXXXX")" && pwd -P)"
    trap fixture_cleanup EXIT INT TERM HUP
    FAKE_HOME="${WORK}/home"
    TREE="${FAKE_HOME}/.local/share/ollama-gateway"
    STORE="${FAKE_HOME}/.ollama/models"
    CANARY_FILE="${FAKE_HOME}/.local/state/ollama-gateway-probe/canary"
    FAKE_BIN="${WORK}/bin"
    mkdir -p "${TREE}/libexec" "${TREE}/home" "${STORE}/manifests" "${STORE}/blobs" \
        "$(dirname "${CANARY_FILE}")" "${FAKE_HOME}/.ssh" "${FAKE_BIN}"
    echo "canary: not a secret" > "${CANARY_FILE}"
    echo "fake private key" > "${FAKE_HOME}/.ssh/id_ed25519"
    echo "store manifest" > "${STORE}/manifests/m"
    KEYCHAIN="${WORK}/probe.keychain-db"
    security create-keychain -p "${KEYCHAIN_PASSWORD}" "${KEYCHAIN}" >/dev/null
    security unlock-keychain -p "${KEYCHAIN_PASSWORD}" "${KEYCHAIN}" >/dev/null
    security add-generic-password -A -s "${CANARY_SERVICE}" -a ollama-gateway \
        -w "not-a-secret" "${KEYCHAIN}" >/dev/null
}

# sandboxed <cmd...> -- run a command under the component's profile with the
# fixture's parameters (the same -D set the launcher passes).
sandboxed() {
    sandboxed_with "${PROFILE}" "$@"
}

# sandboxed_with <profile> <cmd...> -- as sandboxed, with another profile.
sandboxed_with() {
    local profile="$1"
    shift
    sandbox-exec -f "${profile}" \
        -D "USER_HOME=${FAKE_HOME}" \
        -D "GATEWAY_TREE=${TREE}" \
        -D "GATEWAY_HOME=${TREE}/home" \
        -D "MODEL_STORE=${STORE}" \
        "$@"
}

# probe_args -- the probe's fixture arguments, one per line (read into an
# array by the caller; bash 3.2 has no readarray).
probe_args() {
    printf '%s\n' \
        --canary-file "${CANARY_FILE}" \
        --keychain-service "${CANARY_SERVICE}" \
        --keychain "${KEYCHAIN}" \
        --store "${STORE}" \
        --guard-dir "${TREE}/libexec"
}

# --- Assertions --------------------------------------------------------------

fail() {
    echo "FAIL: $*"
    exit 1
}

assert_eq() {
    local got="$1" want="$2" msg="${3:-}"
    [[ "${got}" == "${want}" ]] || fail "${msg}: got '${got}', want '${want}'"
}

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    [[ "${haystack}" == *"${needle}"* ]] || fail "${msg}: expected to find '${needle}' in:
${haystack}"
}

assert_not_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    [[ "${haystack}" != *"${needle}"* ]] || fail "${msg}: did not expect '${needle}' in:
${haystack}"
}

# --- Launcher fixtures -------------------------------------------------------

# free_port -- a loopback TCP port nothing is listening on.
free_port() {
    /usr/bin/python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}

# install_fake_ollama -- an `ollama` on FAKE_BIN that records its argv and
# environment, and whether it could read the file canary and the fake
# ~/.ssh key, into ${WORK}/fake-ollama.out (outside the fake home, so it
# is writable even confined). The launcher scrubs the environment, so the
# output path is baked into the script, not passed in.
install_fake_ollama() {
    cat > "${FAKE_BIN}/ollama" <<FAKE
#!/bin/sh
out="${WORK}/fake-ollama.out"
{
    echo "argv \$*"
    env | sed 's/^/env /'
    if cat "${CANARY_FILE}" >/dev/null 2>&1; then echo "canary readable"; else echo "canary denied"; fi
    if cat "${FAKE_HOME}/.ssh/id_ed25519" >/dev/null 2>&1; then echo "ssh readable"; else echo "ssh denied"; fi
} > "\${out}"
FAKE
    chmod +x "${FAKE_BIN}/ollama"
}

# run_launcher <env assignments...> -- run the ollama launcher as launchd
# would (HOME set, a minimal PATH with the fakes first), against the
# fixture, on a free port. Prints its combined output; returns its status.
run_launcher() {
    env -i HOME="${FAKE_HOME}" PATH="${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin" \
        OLLAMA_GATEWAY_PROBE_KEYCHAIN="${KEYCHAIN}" \
        OLLAMA_GATEWAY_OLLAMA_PORT="${OLLAMA_PORT}" \
        "$@" /bin/zsh -f "${LAUNCH_OLLAMA}" 2>&1
}

# --- Connector fixtures ------------------------------------------------------

TOKEN_SERVICE="lmde.ollama-gateway.tunnel-token"
TOKEN_ACCOUNT="ollama-gateway"
# Shaped like a run token (base64); not a credential.
FAKE_TOKEN="eyJhIjoiZmFrZS1hY2NvdW50IiwidCI6ImZha2UtdHVubmVsIiwicyI6ImZha2UifQ=="

# install_fake_cloudflared -- a `cloudflared` on FAKE_BIN that records its
# argv (one element per line), its environment, and what it read from the
# --token-file path, into ${WORK}/fake-cloudflared.out.
install_fake_cloudflared() {
    cat > "${FAKE_BIN}/cloudflared" <<FAKE
#!/bin/sh
out="${WORK}/fake-cloudflared.out"
: > "\${out}"
prev=""
for a in "\$@"; do
    echo "argv \${a}" >> "\${out}"
    if [ "\${prev}" = "--token-file" ]; then
        echo "token-file-path \${a}" >> "\${out}"
        echo "token-file-content \$(cat "\${a}")" >> "\${out}"
    fi
    prev="\${a}"
done
env | sed 's/^/env /' >> "\${out}"
FAKE
    chmod +x "${FAKE_BIN}/cloudflared"
}

# seed_fake_token [<value>] -- the fake run token into the throwaway keychain.
seed_fake_token() {
    security add-generic-password -U -s "${TOKEN_SERVICE}" -a "${TOKEN_ACCOUNT}" \
        -w "${1:-${FAKE_TOKEN}}" "${KEYCHAIN}" >/dev/null
}

# connector_tree -- the installed connector config the launcher expects.
connector_tree() {
    mkdir -p "${TREE}/connector"
    cp "${COMPONENT_DIR}/connector/config.yml" "${TREE}/connector/config.yml"
}

# run_connector <env assignments...> -- the connector launcher as launchd
# would run it, against the throwaway keychain.
run_connector() {
    env -i HOME="${FAKE_HOME}" PATH="${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin" \
        OLLAMA_GATEWAY_KEYCHAIN="${KEYCHAIN}" \
        "$@" /bin/zsh -f "${LAUNCH_CONNECTOR}" 2>&1
}

# --- Seeding fixtures --------------------------------------------------------

FAKE_REF="op://Example-Vault/example-item/password"

# install_fake_op [<token>] -- an `op` on FAKE_BIN that logs its argv to
# ${WORK}/op.log and answers `op read` with the given token (default
# FAKE_TOKEN); OP_FAKE_FAIL=1 makes it fail like a locked desktop app.
install_fake_op() {
    local token="${1:-${FAKE_TOKEN}}"
    cat > "${FAKE_BIN}/op" <<FAKE
#!/bin/sh
echo "op \$*" >> "${WORK}/op.log"
[ "\${OP_FAKE_FAIL:-}" = "1" ] && { echo "[ERROR] authorization prompt dismissed" >&2; exit 1; }
[ "\$1" = "read" ] || { echo "fake op: unhandled \$*" >&2; exit 99; }
printf '%s' '${token}'
FAKE
    chmod +x "${FAKE_BIN}/op"
}

# install_security_shim -- a `security` on FAKE_BIN that logs its argv and
# its stdin to ${WORK}/security.log, then runs the real one with that stdin.
install_security_shim() {
    cat > "${FAKE_BIN}/security" <<FAKE
#!/bin/sh
echo "argv \$*" >> "${WORK}/security.argv"
exec /usr/bin/security "\$@"
FAKE
    chmod +x "${FAKE_BIN}/security"
}

# run_seed_tty <args...> -- the seeding script under a pseudo-terminal, as a
# human runs it, with the fakes first on PATH and the throwaway keychain.
# Prints its output and always succeeds: script(1) does not carry the
# child's status reliably, so cases assert on output and the keychain.
run_seed_tty() {
    env -i HOME="${FAKE_HOME}" PATH="${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin" TERM=dumb \
        OLLAMA_GATEWAY_KEYCHAIN="${KEYCHAIN}" ${SEED_EXTRA_ENV:-} \
        script -q /dev/null /bin/zsh -f "${SEED}" "$@" < /dev/null 2>&1 | tr -d '\r' || true
}

# keychain_token -- the token now in the throwaway keychain, or nothing.
keychain_token() {
    security find-generic-password -s "${TOKEN_SERVICE}" -a "${TOKEN_ACCOUNT}" -w "${KEYCHAIN}" 2>/dev/null || true
}

# --- Setup fixtures ----------------------------------------------------------

OLLAMA_LABEL="com.tds.lmde.ollama-gateway.ollama"
CONNECTOR_LABEL="com.tds.lmde.ollama-gateway.connector"
PROXY_LABEL="com.tds.lmde.proxy-layer"

# install_fake_launchctl -- a `launchctl` on FAKE_BIN that logs every call to
# ${WORK}/launchctl.log and keeps a loaded-or-not marker per label, so the
# setup scripts' load/unload logic runs without touching launchd.
install_fake_launchctl() {
    mkdir -p "${WORK}/launchd"
    cat > "${FAKE_BIN}/launchctl" <<FAKE
#!/bin/sh
echo "launchctl \$*" >> "${WORK}/launchctl.log"
state="${WORK}/launchd"
case "\$1" in
    print) [ -e "\${state}/\$(basename "\$2")" ] ;;
    bootstrap) label=\$(/usr/libexec/PlistBuddy -c 'Print :Label' "\$3") && touch "\${state}/\${label}" ;;
    bootout) rm -f "\${state}/\$(basename "\$2")" ;;
    kickstart|enable|disable) exit 0 ;;
    *) echo "fake launchctl: unhandled \$*" >&2; exit 99 ;;
esac
FAKE
    chmod +x "${FAKE_BIN}/launchctl"
}

# everyday_fixture -- the everyday ollama's footprint in the fake home: its
# LaunchAgent, identity key, history, config and a populated store.
everyday_fixture() {
    mkdir -p "${FAKE_HOME}/Library/LaunchAgents" "${STORE}/manifests/registry.ollama.ai/library/m"
    cat > "${FAKE_HOME}/Library/LaunchAgents/sh.brew.ollama.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>sh.brew.ollama</string>
<key>ProgramArguments</key><array><string>/opt/homebrew/opt/ollama/bin/ollama</string><string>serve</string></array>
</dict></plist>
PLIST
    echo "everyday identity" > "${FAKE_HOME}/.ollama/id_ed25519"
    echo "everyday history" > "${FAKE_HOME}/.ollama/history"
    echo '{}' > "${FAKE_HOME}/.ollama/config.json"
    echo '{"layers":[]}' > "${STORE}/manifests/registry.ollama.ai/library/m/latest"
    echo "weights" > "${STORE}/blobs/sha256-0000"
}

# everyday_snapshot -- a digest of every path, size, mode, mtime and content
# hash in the everyday ollama's footprint.
everyday_snapshot() {
    {
        find "${FAKE_HOME}/.ollama" "${FAKE_HOME}/Library/LaunchAgents/sh.brew.ollama.plist" \
            -exec stat -f '%N %z %p %m' {} + | sort
        find "${FAKE_HOME}/.ollama" -type f -exec shasum {} + | sort
        shasum "${FAKE_HOME}/Library/LaunchAgents/sh.brew.ollama.plist"
    } | shasum | awk '{print $1}'
}

# run_setup <args...> -- the gateway's setup.sh against the fake home, with
# fake launchctl, the throwaway keychain and a throwaway proxy-layer root.
run_setup() {
    env -i HOME="${FAKE_HOME}" PATH="${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin" \
        OLLAMA_GATEWAY_KEYCHAIN="${KEYCHAIN}" \
        "${SETUP}" "$@" 2>&1
}

# plist_value <plist> <key path> -- PlistBuddy's view of one value.
plist_value() {
    /usr/libexec/PlistBuddy -c "Print :$2" "$1" 2>/dev/null
}
