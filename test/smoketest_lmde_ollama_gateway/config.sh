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
