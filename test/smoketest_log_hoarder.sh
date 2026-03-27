#!/bin/zsh
# smoketest_log_hoarder.sh — end-to-end smoke test for log-hoarder
#
# Spins up throwaway tmux sessions, triggers hooks, and asserts on
# log directory state.  Requires: tmux.
#
# NOTE: pipe-pane behaviour (actual log file creation) is verified manually,
# not here.  tmux hooks fire the logging script inside the server, and
# pipe-pane file creation depends on pane I/O timing that is unreliable
# in automated tests.  This suite tests: directory layout, shepherd logic,
# and the "suppressed" code path.
#
# Usage: ./test/smoketest_log_hoarder.sh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
LOGGING_SH="${REPO_DIR}/bin/tmux_logging.sh"
SHEPHERD_SH="${REPO_DIR}/bin/tmux_shepherd.sh"
ORIG_TDS_LOG_DIR=""

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
TEST_TDS_LOG_DIR=""
CLEANUP_SESSIONS=()

red()   { print -n "\033[1;31m$1\033[0m"; }
green() { print -n "\033[1;32m$1\033[0m"; }
bold()  { print -n "\033[1m$1\033[0m"; }

assert() {
    local label="$1" condition="$2"
    (( TESTS_RUN++ )) || true
    if eval "${condition}"; then
        green "  PASS"; print " ${label}"
        (( TESTS_PASSED++ )) || true
    else
        red "  FAIL"; print " ${label}"
        (( TESTS_FAILED++ )) || true
    fi
}

setup() {
    TEST_TDS_LOG_DIR=$(mktemp -d "${TMPDIR:-/tmp}/log-hoarder-test.XXXXXX")
    export TDS_LOG_DIR="${TEST_TDS_LOG_DIR}"
    mkdir -p "${TDS_LOG_DIR}/active" "${TDS_LOG_DIR}/archived"

    # Override TDS_LOG_DIR in tmux's global environment so that run-shell
    # subprocesses (which source .zshenv with ${TDS_LOG_DIR:-default})
    # inherit the test value.
    ORIG_TDS_LOG_DIR=$(tmux show-environment -g TDS_LOG_DIR 2>/dev/null | sed 's/^TDS_LOG_DIR=//' || true)
    tmux set-environment -g TDS_LOG_DIR "${TDS_LOG_DIR}"
}

cleanup() {
    for s in "${CLEANUP_SESSIONS[@]}"; do
        tmux kill-session -t "${s}" 2>/dev/null || true
    done
    # Restore original TDS_LOG_DIR in tmux global env.
    if [[ -n "${ORIG_TDS_LOG_DIR:-}" ]]; then
        tmux set-environment -g TDS_LOG_DIR "${ORIG_TDS_LOG_DIR}"
    else
        tmux set-environment -g -u TDS_LOG_DIR 2>/dev/null || true
    fi
    if [[ -n "${TEST_TDS_LOG_DIR}" ]]; then
        rm -rf "${TEST_TDS_LOG_DIR}"
    fi
}
trap cleanup EXIT

# --- Helper functions ---

# Create a detached tmux session and run the logging hook against it.
create_logged_session() {
    local name="$1"
    tmux new-session -d -s "${name}"
    CLEANUP_SESSIONS+=("${name}")
    # The session-created hook from tmux.conf fires automatically.
    # Give it a moment to complete.
    sleep 1
}

# --- Tests ---

test_logging_creates_active_dir() {
    bold "Test: logging hook creates active directory and diag log\n"

    create_logged_session "smoke-log"

    local active="${TDS_LOG_DIR}/active/smoke-log/0/0"
    assert "active pane dir exists"      "[[ -d '${active}' ]]"

    local diag="${TDS_LOG_DIR}/log-hoarder.logging.log"
    assert "diag log exists"             "[[ -f '${diag}' ]]"
    assert "diag log shows pipe opened"  "grep -q 'pipe opened' '${diag}'"
}

test_shepherd_skips_alive_session() {
    bold "\nTest: shepherd refuses to archive a live session\n"

    create_logged_session "smoke-alive"

    local active="${TDS_LOG_DIR}/active/smoke-alive/0/0"
    assert "active dir exists before shepherd" "[[ -d '${active}' ]]"

    # Call shepherd as if the hook told it to archive this (still-alive) session.
    TDS_LOG_DIR="${TDS_LOG_DIR}" /bin/zsh -f "${SHEPHERD_SH}" "smoke-alive" "0" "0"

    assert "active dir still exists (not archived)" "[[ -d '${active}' ]]"

    local archived="${TDS_LOG_DIR}/archived/smoke-alive"
    assert "archived dir does NOT exist" "[[ ! -d '${archived}' ]]"

    local diag="${TDS_LOG_DIR}/log-hoarder.shepherd.hook.log"
    assert "diag shows 'still alive' skip" "grep -q 'still alive' '${diag}'"
}

test_shepherd_archives_dead_session() {
    bold "\nTest: shepherd archives a dead session via orphan sweep\n"

    create_logged_session "smoke-dead"

    local active="${TDS_LOG_DIR}/active/smoke-dead/0/0"
    assert "active dir exists before kill" "[[ -d '${active}' ]]"

    # Kill the session, then run shepherd.
    tmux kill-session -t "smoke-dead" 2>/dev/null || true

    # Shepherd in hook mode — target is the dead session.
    TDS_LOG_DIR="${TDS_LOG_DIR}" /bin/zsh -f "${SHEPHERD_SH}" "smoke-dead" "0" "0"

    local archived="${TDS_LOG_DIR}/archived/smoke-dead/0/0"
    assert "archived dir exists"          "[[ -d '${archived}' ]]"
    assert "active dir is gone"           "[[ ! -d '${active}' ]]"
}

test_logging_suppressed_without_tds_log_dir() {
    bold "\nTest: logging suppressed when TDS_LOG_DIR is empty\n"

    local diag="${HOME}/log-hoarder.logging.log"
    rm -f "${diag}"

    # Run directly with zsh -f (skip .zshenv) and empty TDS_LOG_DIR.
    # This tests the code path, not the tmux hook wiring.
    TDS_LOG_DIR="" /bin/zsh -f "${LOGGING_SH}"

    assert "diag log written to \$HOME"   "[[ -f '${diag}' ]]"
    assert "diag says logging suppressed"  "grep -q 'logging suppressed' '${diag}'"

    rm -f "${diag}"
}

# --- Main ---

main() {
    bold "═══ log-hoarder smoke test ═══\n\n"

    setup
    test_logging_creates_active_dir
    test_shepherd_skips_alive_session
    test_shepherd_archives_dead_session
    test_logging_suppressed_without_tds_log_dir

    print ""
    bold "═══ Results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    if (( TESTS_FAILED > 0 )); then
        red ", ${TESTS_FAILED} failed"
    fi
    print " ═══"

    (( TESTS_FAILED == 0 ))
}

main "$@"
