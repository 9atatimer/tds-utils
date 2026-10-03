#!/usr/bin/env bash
# smoketest_designomatic_pin.sh -- the pinned designomatic starts on this
# machine (issue #404).
#
# Real-system, not hermetic: installs the exact DESIGNOMATIC_VERSION that
# lmde/lib/pins.env pins, from GitHub Packages, into a throwaway prefix, and
# runs it. The acquire suite stubs npm, so it can never see a pinned release
# that cannot start on real hardware -- 0.1.0 bundled a Linux x86_64 gRPC
# extension and died at import on macOS arm64 (template-tools#792), and the
# rail kept installing it after the fix shipped.
#
# Isolated: the package prefix and designomatic's XDG data, config and cache
# all live in a temp directory, so neither the acquired install nor the
# user's designomatic configuration (and its 1Password provisioning) is
# touched. Uses the user's npm registry credential as acquire does.
#
# SKIPs, never fails, when npm is absent or the registry cannot serve the
# pinned version (offline, no credential). First run takes about a minute:
# 0.3.0 and later build their environment with uv.
#
# Usage: ./test/smoketest_designomatic_pin.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
PINS="${REPO_DIR}/lmde/lib/pins.env"
PACKAGE="@nine-at-a-time-media/designomatic"
REGISTRY="https://npm.pkg.github.com"

WORKROOT=""

# --- Helpers -----------------------------------------------------------------

pass() { printf '  PASS %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; }
skip() { printf '  SKIP %s\n' "$1"; }

cleanup() { [ -n "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT INT TERM HUP

# --- Action functions --------------------------------------------------------

pinned_version() {
    # shellcheck disable=SC1090
    ( . "${PINS}"; printf '%s\n' "${DESIGNOMATIC_VERSION:-}" )
}

install_pinned() {
    local version="$1"
    npm install --silent --no-audit --no-fund --prefix "${WORKROOT}/prefix" \
        --registry "${REGISTRY}" "${PACKAGE}@${version}" >"${WORKROOT}/install.log" 2>&1
}

run_designomatic() {
    # Run the way an agent does: from the repo, `designomatic panels list --json`.
    ( cd "${REPO_DIR}" && \
      XDG_DATA_HOME="${WORKROOT}/xdg/data" \
      XDG_CONFIG_HOME="${WORKROOT}/xdg/config" \
      XDG_CACHE_HOME="${WORKROOT}/xdg/cache" \
      "${WORKROOT}/prefix/node_modules/.bin/designomatic" panels list --json )
}

# --- Flow --------------------------------------------------------------------

run_smoketest() {
    local version out
    printf 'smoketest_designomatic_pin\n'
    command -v npm >/dev/null 2>&1 || { skip "npm not on PATH"; return 0; }

    version="$(pinned_version)"
    if [ -z "${version}" ] || [ "${version}" = "UNSET" ]; then
        fail "lmde/lib/pins.env pins no DESIGNOMATIC_VERSION"
        return 1
    fi

    WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/designomatic-pin-smoke.XXXXXX")"
    if ! install_pinned "${version}"; then
        skip "cannot install ${PACKAGE}@${version} from ${REGISTRY} (offline or no credential)"
        return 0
    fi

    # Given the pinned version, When it runs as an agent runs it, Then it
    # starts and answers with JSON.
    if out="$(run_designomatic 2>"${WORKROOT}/run.err")" && printf '%s\n' "${out}" | grep -qE '^\[(\])?$'; then
        pass "pinned designomatic ${version} starts and lists panels on $(uname -sm)"
        return 0
    fi
    fail "pinned designomatic ${version} does not start on $(uname -sm)"
    tail -5 "${WORKROOT}/run.err" | sed 's/^/    /'
    return 1
}

# --- Main --------------------------------------------------------------------

main() {
    run_smoketest
}

main "$@"
