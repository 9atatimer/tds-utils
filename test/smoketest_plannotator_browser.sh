#!/usr/bin/env bash
# smoketest_plannotator_browser.sh -- behavioral smoke test for
# bin/plannotator-browser, the $PLANNOTATOR_BROWSER handler that makes
# Plannotator's review surface open in its OWN Chrome window (issue #266).
#
# Hermetic: no network, no sleeps, and Chrome is never launched. Each case puts
# a stub `open` first on PATH that records its argv to a file, then drives the
# handler at it and asserts on what was recorded.
#
# The assertions encode the two facts that make or break the behavior, both
# established from the plugin's packages/server/browser.ts:
#   1. `-n` must be present. Without it `open -a "Google Chrome"` merely
#      activates the running instance and DISCARDS --args, which is exactly the
#      tab-instead-of-window symptom.
#   2. The handler must be a real executable at an absolute path, because the
#      plugin only exec's $PLANNOTATOR_BROWSER directly when it contains a "/";
#      a bare name degrades to `open -a <name> <url>`.
#
# Runs on both CI legs. The argv cases are macOS-only -- the handler refuses to
# run elsewhere by design -- and are skipped on Linux; the dot.zshenv wiring
# cases are pure greps and run everywhere.
#
# Usage: ./test/smoketest_plannotator_browser.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
HANDLER="${REPO_DIR}/bin/plannotator-browser"
ZSHENV="${REPO_DIR}/macos/dot.zshenv"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1"
    local condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

cleanup() { [ -n "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixture ---------------------------------------------------------------

STUBDIR=""
ARGV_LOG=""

# make_stub_open -- a fake `open` that records its argv, one argument per line,
# and exits 0. Placed first on PATH so the handler cannot reach the real one.
make_stub_open() {
    STUBDIR="${WORKROOT}/stub"
    ARGV_LOG="${WORKROOT}/argv.log"
    mkdir -p "${STUBDIR}"
    : > "${ARGV_LOG}"
    cat > "${STUBDIR}/open" <<STUB
#!/bin/sh
for a in "\$@"; do printf '%s\n' "\$a" >> "${ARGV_LOG}"; done
exit 0
STUB
    chmod +x "${STUBDIR}/open"
}

# run_handler <url> -- drive the handler with the stub in front of PATH.
run_handler() {
    PATH="${STUBDIR}:${PATH}" "${HANDLER}" "$1"
}

# logged <string> -- did the stub receive exactly this argument?
#
# The `--` is load-bearing: the arguments under test include `-n` and
# `--new-window`, which grep would otherwise parse as its own flags and then
# block forever reading stdin with no file operand.
logged() {
    grep -qxF -- "$1" "${ARGV_LOG}" < /dev/null
}

# --- Flow functions --------------------------------------------------------

test_handler_exists() {
    bold "handler is installable"; printf '\n'
    assert "bin/plannotator-browser exists"      "[ -f '${HANDLER}' ]"
    assert "bin/plannotator-browser executable"  "[ -x '${HANDLER}' ]"
}

test_forces_new_window() {
    bold "forces a new window, not a tab"; printf '\n'
    make_stub_open
    run_handler "http://127.0.0.1:4321/plan/abc"

    assert "passes -n (new instance; without it --args is discarded)" \
        "logged '-n'"
    assert "targets Google Chrome" \
        "logged 'Google Chrome'"
    assert "passes --args so the flags reach Chrome" \
        "logged '--args'"
    assert "passes --new-window" \
        "logged '--new-window'"
    assert "passes the URL through unchanged" \
        "logged 'http://127.0.0.1:4321/plan/abc'"
}

test_url_not_word_split() {
    bold "URL is passed as one argument"; printf '\n'
    make_stub_open
    run_handler "http://127.0.0.1:4321/plan/a b&c"

    assert "a URL containing a space survives as a single argv entry" \
        "logged 'http://127.0.0.1:4321/plan/a b&c'"
}

test_zshenv_exports_handler() {
    bold "dot.zshenv wires it up"; printf '\n'
    assert "macos/dot.zshenv exports PLANNOTATOR_BROWSER" \
        "grep -q '^export PLANNOTATOR_BROWSER=' '${ZSHENV}'"
    assert "the exported value is an absolute path (a bare name degrades to a tab)" \
        "grep -qE '^export PLANNOTATOR_BROWSER=\"[^\"]*/[^\"]*\"' '${ZSHENV}'"
    assert "it points at the ~/.local/bin symlink, per the AST_MCP_BIN precedent" \
        "grep -q '^export PLANNOTATOR_BROWSER=.*\$HOME/.local/bin/plannotator-browser' '${ZSHENV}'"
    assert "the default is overridable, like TDS_LOG_DIR and AST_MCP_BIN" \
        "grep -q '^export PLANNOTATOR_BROWSER=\"\${PLANNOTATOR_BROWSER:-' '${ZSHENV}'"
}

run_all() {
    WORKROOT="$(mktemp -d)"
    test_handler_exists
    # The exec-driven cases would abort the suite under `set -e` with a bare
    # 127 if the handler is absent, hiding every later assertion behind one
    # missing file. Report them as skipped instead; test_handler_exists has
    # already failed, so the suite still exits non-zero.
    if [ ! -x "${HANDLER}" ]; then
        bold "forces a new window, not a tab"; printf '\n'
        printf '  SKIP handler absent -- see the failure above\n'
    elif [ "$(uname -s)" != "Darwin" ]; then
        # The handler refuses to run off macOS by design (it exists to drive
        # open(1)), so the argv cases have nothing to assert on the Linux CI
        # leg. Skip, never xfail: the grep-only cases below still run there and
        # keep the dot.zshenv wiring honest on both legs.
        bold "forces a new window, not a tab"; printf '\n'
        printf '  SKIP not macOS (handler is open(1)-based by design)\n'
    else
        test_forces_new_window
        test_url_not_word_split
    fi
    test_zshenv_exports_handler

    printf '\n'
    bold "${TESTS_PASSED}/${TESTS_RUN} passed"; printf '\n'
    [ "${TESTS_FAILED}" -eq 0 ]
}

# --- Main ------------------------------------------------------------------

main() {
    run_all
}

main "$@"
