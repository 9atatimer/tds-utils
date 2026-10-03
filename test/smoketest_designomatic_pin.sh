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
# Isolated: the package prefix, the npm config and designomatic's XDG data,
# config and cache all live in a temp directory, so neither the acquired
# install nor the user's designomatic configuration is touched, and
# DESIGNOMATIC_NO_AUTO_OP=1 keeps designomatic from wrapping itself in
# `op run` (it reads ~/.config/designomatic.env whatever XDG_CONFIG_HOME says,
# and the 1Password prompt that follows makes the result depend on the
# vault's lock state). The registry credential resolves the way
# acquire's does: GH_PAT_NAATM_PACKAGES_RO, then GH_AI_TOOLS_PAT, then
# `gh auth token`.
#
# SKIPs, never fails, when a prerequisite is missing (npm; uv, which 0.3.0
# and later need to build their environment on first run) or the registry
# cannot be reached or authenticated. Any other install or start failure is
# a FAIL. Each step is bounded, so the test cannot hang. First run takes
# about a minute.
#
# Usage: ./test/smoketest_designomatic_pin.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
PINS="${REPO_DIR}/lmde/lib/pins.env"
PACKAGE="@nine-at-a-time-media/designomatic"
REGISTRY="https://npm.pkg.github.com"
STEP_SECONDS=600

WORKROOT=""

# --- Helpers -----------------------------------------------------------------

pass() { printf '  PASS %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; }
skip() { printf '  SKIP %s\n' "$1"; }

cleanup() {
    if [ -n "${WORKROOT}" ]; then
        rm -rf "${WORKROOT}"
    fi
    return 0
}
trap cleanup EXIT INT TERM HUP

# bounded <seconds> <cmd...> -- run cmd, killed by SIGALRM past the limit.
bounded() {
    local seconds="$1"
    shift
    perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "${seconds}" "$@"
}

# --- Action functions --------------------------------------------------------

pinned_version() {
    # shellcheck disable=SC1090
    ( . "${PINS}"; printf '%s\n' "${DESIGNOMATIC_VERSION:-}" )
}

registry_token() {
    if [ -n "${GH_PAT_NAATM_PACKAGES_RO:-}" ]; then
        printf '%s\n' "${GH_PAT_NAATM_PACKAGES_RO}"
    elif [ -n "${GH_AI_TOOLS_PAT:-}" ]; then
        printf '%s\n' "${GH_AI_TOOLS_PAT}"
    elif command -v gh >/dev/null 2>&1; then
        bounded 10 gh auth token --hostname github.com 2>/dev/null || true
    fi
}

write_npmrc() {
    local token="$1" npmrc="${WORKROOT}/npmrc"
    ( umask 077
      printf '@nine-at-a-time-media:registry=%s\n' "${REGISTRY}" > "${npmrc}"
      if [ -n "${token}" ]; then
          printf '//npm.pkg.github.com/:_authToken=%s\n' "${token}" >> "${npmrc}"
      fi )
    printf '%s\n' "${npmrc}"
}

install_pinned() {
    local version="$1" npmrc="$2"
    bounded "${STEP_SECONDS}" npm install --no-audit --no-fund \
        --userconfig "${npmrc}" --prefix "${WORKROOT}/prefix" \
        "${PACKAGE}@${version}" >"${WORKROOT}/install.log" 2>&1
}

# install_unreachable -- did the install fail because the registry could not
# be reached or would not authenticate us (a SKIP), rather than for a reason
# that is the pin's fault (a FAIL)?
install_unreachable() {
    grep -qE 'E401|E403|ENEEDAUTH|ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ECONNRESET|ETIMEDOUT|network' \
        "${WORKROOT}/install.log"
}

run_designomatic() {
    # Run the way an agent does: from the repo, `designomatic panels list --json`.
    ( cd "${REPO_DIR}" && \
      XDG_DATA_HOME="${WORKROOT}/xdg/data" \
      XDG_CONFIG_HOME="${WORKROOT}/xdg/config" \
      XDG_CACHE_HOME="${WORKROOT}/xdg/cache" \
      DESIGNOMATIC_NO_AUTO_OP=1 \
      bounded "${STEP_SECONDS}" \
          "${WORKROOT}/prefix/node_modules/.bin/designomatic" panels list --json )
}

# --- Flow --------------------------------------------------------------------

run_smoketest() {
    local version npmrc out
    printf 'smoketest_designomatic_pin\n'
    command -v npm >/dev/null 2>&1 || { skip "npm not on PATH"; return 0; }

    version="$(pinned_version)"
    if [ -z "${version}" ] || [ "${version}" = "UNSET" ]; then
        fail "lmde/lib/pins.env pins no DESIGNOMATIC_VERSION"
        return 1
    fi

    WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/designomatic-pin-smoke.XXXXXX")"
    npmrc="$(write_npmrc "$(registry_token)")"
    if ! install_pinned "${version}" "${npmrc}"; then
        if install_unreachable; then
            skip "registry unreachable or unauthenticated for ${PACKAGE}@${version}"
            tail -3 "${WORKROOT}/install.log" | sed 's/^/    /'
            return 0
        fi
        fail "cannot install pinned ${PACKAGE}@${version}"
        tail -5 "${WORKROOT}/install.log" | sed 's/^/    /'
        return 1
    fi

    if grep -q 'Prerequisites: uv' "${WORKROOT}/prefix/node_modules/.bin/designomatic" 2>/dev/null \
            && ! command -v uv >/dev/null 2>&1; then
        skip "designomatic ${version} needs uv on PATH to build its environment"
        return 0
    fi

    # Given the pinned version, When it runs as an agent runs it, Then it
    # starts and answers with its JSON list (json.dumps(..., indent=2): the
    # first line is "[" or, for no panels, "[]").
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
