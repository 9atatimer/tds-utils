#!/usr/bin/env bash
# smoketest_comfyui_launchd.sh -- behavioral smoke test for bin/launch-comfyui
# and macos/launchd/com.tds.comfyui.plist (issue #338).
#
# Exercises the launcher's --dry-run seam against a throwaway fixture tree
# (stub venv python, empty main.py) so nothing real is launched and torch is
# never imported. Real lsof, real nc, real plutil -- the preflight checks are
# the point, so they run against the actual macOS tools.
#
# Skips cleanly on non-macOS.
#
# Usage: ./test/smoketest_comfyui_launchd.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
LAUNCHER="${REPO_DIR}/bin/launch-comfyui"
PLIST="${REPO_DIR}/macos/launchd/com.tds.comfyui.plist"

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""
NC_PID=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1" condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

skip() { bold "  SKIP"; printf ' %s\n' "$1"; }

setup() { WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/comfyui-launchd-test.XXXXXX")"; }
cleanup() {
    # Stop by PID and confirm; never a jobspec (AGENT.global.md).
    if [ -n "${NC_PID}" ] && kill -0 "${NC_PID}" 2>/dev/null; then
        kill "${NC_PID}" 2>/dev/null || true
    fi
    if [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ]; then
        rm -rf "${WORKROOT}"
    fi
    return 0
}
trap cleanup EXIT

# --- Fixtures ---

# A fake ComfyUI base (venv with an executable python stub) and source tree
# (an empty main.py). The launcher must only stat these under --dry-run.
make_fixture() {
    local base="${WORKROOT}/base" src="${WORKROOT}/src"
    mkdir -p "${base}/.venv/bin" "${base}/user" "${src}"
    printf '#!/bin/sh\nexit 0\n' > "${base}/.venv/bin/python"
    chmod +x "${base}/.venv/bin/python"
    : > "${src}/main.py"
}

TOTAL_GB=""
total_gb() {
    if [ -z "${TOTAL_GB}" ]; then
        TOTAL_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
    fi
    printf '%s' "${TOTAL_GB}"
}

# dry_run <extra env assignments...> -- runs the launcher's dry-run against
# the fixture with a fixed recommended max so the ratio math is deterministic.
dry_run() {
    env COMFYUI_BASE="${WORKROOT}/base" COMFYUI_SRC="${WORKROOT}/src" \
        COMFYUI_RECOMMENDED_MAX_GB=50 COMFYUI_BUDGET_GB=40 "$@" \
        "${LAUNCHER}" --dry-run
}

# --- Tests ---

test_dry_run_derives_caps() {
    bold "Dry run derives both caps from one budget"; printf '\n'
    local out reserve
    reserve=$(( $(total_gb) - 40 ))
    out="$(dry_run 2>&1)" || true

    assert "high watermark is budget / recommended max (40/50)" \
        "grep -qx 'env PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.80' <<< \"\${out}\""
    assert "low watermark is high minus 0.1" \
        "grep -qx 'env PYTORCH_MPS_LOW_WATERMARK_RATIO=0.70' <<< \"\${out}\""
    assert "--reserve-vram is total minus budget (${reserve})" \
        "grep -A1 -x 'argv --reserve-vram' <<< \"\${out}\" | grep -qx 'argv ${reserve}'"
    assert "server binds loopback only" \
        "grep -A1 -x 'argv --listen' <<< \"\${out}\" | grep -qx 'argv 127.0.0.1'"
    assert "default port is 8188" \
        "grep -A1 -x 'argv --port' <<< \"\${out}\" | grep -qx 'argv 8188'"
    assert "node output cache is bounded (--cache-lru)" \
        "grep -qx 'argv --cache-lru' <<< \"\${out}\""
    assert "venv python is argv[0]" \
        "grep -qx 'argv ${WORKROOT}/base/.venv/bin/python' <<< \"\${out}\""
    assert "main.py from COMFYUI_SRC is argv[1]" \
        "grep -qx 'argv ${WORKROOT}/src/main.py' <<< \"\${out}\""
    assert "no Desktop-only --front-end-root" \
        "! grep -q 'front-end-root' <<< \"\${out}\""
    assert "no --disable-smart-memory (a copy within the same pool)" \
        "! grep -q 'disable-smart-memory' <<< \"\${out}\""
    assert "dry run does not exec the stub python" \
        "dry_run >/dev/null 2>&1"
}

test_overrides_honored() {
    bold "Env overrides reach argv"; printf '\n'
    local out
    out="$(dry_run COMFYUI_PORT=9999 COMFYUI_CACHE_LRU=7 2>&1)" || true

    assert "COMFYUI_PORT=9999 shows up" \
        "grep -A1 -x 'argv --port' <<< \"\${out}\" | grep -qx 'argv 9999'"
    assert "COMFYUI_CACHE_LRU=7 shows up" \
        "grep -A1 -x 'argv --cache-lru' <<< \"\${out}\" | grep -qx 'argv 7'"
}

test_preflight_refuses() {
    bold "Preflight refuses bad states with a named reason"; printf '\n'
    local out status total

    status=0
    out="$(env COMFYUI_BASE="${WORKROOT}/nope" COMFYUI_SRC="${WORKROOT}/src" \
        COMFYUI_RECOMMENDED_MAX_GB=50 "${LAUNCHER}" --dry-run 2>&1)" || status=$?
    assert "missing venv python exits non-zero" "[ ${status} -ne 0 ]"
    assert "missing venv python names the path" \
        "grep -q '${WORKROOT}/nope/.venv/bin/python' <<< \"\${out}\""

    total="$(total_gb)"
    status=0
    out="$(dry_run COMFYUI_BUDGET_GB="${total}" 2>&1)" || status=$?
    assert "budget equal to total RAM (${total}) is rejected" "[ ${status} -ne 0 ]"

    status=0
    out="$(dry_run COMFYUI_BUDGET_GB=0 2>&1)" || status=$?
    assert "budget of 0 is rejected" "[ ${status} -ne 0 ]"

    status=0
    out="$(dry_run COMFYUI_BUDGET_GB=abc 2>&1)" || status=$?
    assert "non-integer budget is rejected" "[ ${status} -ne 0 ]"
}

test_port_in_use() {
    bold "Preflight refuses a port that is already bound"; printf '\n'
    local port=18188 out status tries=0

    nc -l 127.0.0.1 "${port}" >/dev/null 2>&1 &
    NC_PID=$!
    while ! lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; do
        tries=$((tries + 1))
        if [ "${tries}" -ge 20 ]; then
            skip "could not bind a throwaway listener on ${port}"
            return
        fi
        sleep 0.1
    done

    status=0
    out="$(dry_run COMFYUI_PORT="${port}" 2>&1)" || status=$?
    assert "bound port exits non-zero" "[ ${status} -ne 0 ]"
    assert "bound port is named in the message" "grep -q '${port}' <<< \"\${out}\""

    kill "${NC_PID}"
    tries=0
    while kill -0 "${NC_PID}" 2>/dev/null; do
        tries=$((tries + 1))
        [ "${tries}" -ge 20 ] && break
        sleep 0.1
    done
    assert "throwaway listener is gone" "! kill -0 '${NC_PID}' 2>/dev/null"
    NC_PID=""
}

test_plist() {
    bold "launchd plist is well-formed and consistent"; printf '\n'
    assert "plist exists" "[ -f '${PLIST}' ]"
    assert "plutil -lint passes" "plutil -lint '${PLIST}' >/dev/null 2>&1"
    assert "Label matches filename" \
        "[ \"\$(/usr/libexec/PlistBuddy -c 'Print :Label' '${PLIST}' 2>/dev/null)\" = 'com.tds.comfyui' ]"
    assert "RunAtLoad is false (on demand, not at login)" \
        "[ \"\$(/usr/libexec/PlistBuddy -c 'Print :RunAtLoad' '${PLIST}' 2>/dev/null)\" = 'false' ]"
    assert "ProcessType is Background (UI keeps priority during a run)" \
        "[ \"\$(/usr/libexec/PlistBuddy -c 'Print :ProcessType' '${PLIST}' 2>/dev/null)\" = 'Background' ]"
    assert "KeepAlive restarts on crash only" \
        "[ \"\$(/usr/libexec/PlistBuddy -c 'Print :KeepAlive:Crashed' '${PLIST}' 2>/dev/null)\" = 'true' ]"
    assert "ThrottleInterval prevents a hot restart loop" \
        "[ \"\$(/usr/libexec/PlistBuddy -c 'Print :ThrottleInterval' '${PLIST}' 2>/dev/null)\" -ge 10 ]"
    assert "launches the bare command name (tds_bin tiering via .zshenv)" \
        "grep -q 'exec launch-comfyui' '${PLIST}'"
    assert "no StandardOutPath: launcher owns the log under ~/Library/Logs" \
        "[ -f '${PLIST}' ] && ! grep -q 'StandardOutPath</key>' '${PLIST}'"
}

# --- Main ---

main() {
    bold "smoketest_comfyui_launchd"; printf '\n\n'

    if [ "$(uname -s)" != "Darwin" ]; then
        skip "not macOS; launchd and MPS do not apply"
        exit 0
    fi

    setup
    make_fixture

    if [ ! -x "${LAUNCHER}" ]; then
        red "  FAIL"; printf ' launcher missing or not executable: %s\n' "${LAUNCHER}"
        TESTS_RUN=1; TESTS_FAILED=1
    else
        test_dry_run_derives_caps
        test_overrides_honored
        test_preflight_refuses
        test_port_in_use
    fi
    test_plist

    printf '\n'
    if [ "${TESTS_FAILED}" -eq 0 ]; then
        green "All ${TESTS_RUN} checks passed."; printf '\n'
        exit 0
    fi
    red "${TESTS_FAILED} of ${TESTS_RUN} checks failed."; printf '\n'
    exit 1
}

main "$@"
