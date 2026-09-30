#!/bin/zsh
# smoketest_tmux_launch.sh -- one terminal, one window in ONE shared tmux session
#
# Runs bin/tmux-launch against a PRIVATE tmux server (`tmux -L <socket>`), with
# the attach step skipped (TDS_TMUX_NO_ATTACH=1): attaching needs a terminal,
# and everything before it is where the behavior lives.  Requires: tmux.
#
# Covered: first terminal creates the session, later terminals add a window to
# it instead of creating another session, and a new window starts in the
# directory the terminal was opened in.  Also the dot.zshrc wiring: an
# interactive shell outside tmux hands off to tmux-launch.
#
# Usage: ./test/smoketest_tmux_launch.sh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
LAUNCH_SH="${REPO_DIR}/bin/tmux-launch"
DOT_ZSHRC="${REPO_DIR}/macos/dot.zshrc"
SOCKET="tmux-launch-smoke-$$"
SCRATCH=""

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

red()   { print -n "\033[1;31m$1\033[0m"; }
green() { print -n "\033[1;32m$1\033[0m"; }
bold()  { print -n "\033[1m$1\033[0m"; }

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    (( TESTS_RUN++ )) || true
    if [[ "${expected}" == "${actual}" ]]; then
        green "  PASS"; print " ${label}"
        (( TESTS_PASSED++ )) || true
    else
        red "  FAIL"; print " ${label} (expected '${expected}', got '${actual}')"
        (( TESTS_FAILED++ )) || true
    fi
}

# --- Helpers ---

tm() { tmux -L "${SOCKET}" "$@"; }

# What a new terminal does, minus the attach. $1 is the terminal's cwd.
open_terminal() {
    ( cd "$1" && TDS_TMUX_SOCKET="${SOCKET}" TDS_TMUX_NO_ATTACH=1 /bin/zsh -f "${LAUNCH_SH}" ) || true
}

session_count() { tm list-sessions 2>/dev/null | grep -c . || true; }

window_count() { tm list-windows -t main 2>/dev/null | grep -c . || true; }

setup() {
    SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/tmux-launch-test.XXXXXX")
    mkdir -p "${SCRATCH}/term1" "${SCRATCH}/term2"
}

cleanup() {
    tmux -L "${SOCKET}" kill-server 2>/dev/null || true
    [[ -n "${SCRATCH}" ]] && rm -rf "${SCRATCH}"
}
trap cleanup EXIT

# --- Tests ---

test_first_terminal_creates_the_session() {
    bold "Test: the first terminal creates session 'main' with one window\n"
    tm kill-server 2>/dev/null || true

    open_terminal "${SCRATCH}/term1"

    assert_eq "one session" 1 "$(session_count)"
    assert_eq "it is named main" main "$(tm list-sessions -F '#S' | head -1)"
    assert_eq "with one window" 1 "$(window_count)"
}

test_second_terminal_adds_a_window_not_a_session() {
    bold "\nTest: a later terminal adds a window to the running session\n"

    open_terminal "${SCRATCH}/term2"

    assert_eq "still one session" 1 "$(session_count)"
    assert_eq "now two windows" 2 "$(window_count)"

    open_terminal "${SCRATCH}/term1"
    assert_eq "third terminal: still one session" 1 "$(session_count)"
    assert_eq "third terminal: three windows" 3 "$(window_count)"
}

test_new_window_starts_in_the_terminals_directory() {
    bold "\nTest: the new window starts where the terminal was opened\n"

    open_terminal "${SCRATCH}/term2"

    local newest
    newest=$(tm list-windows -t main -F '#{window_index} #{pane_current_path}' | sort -n | tail -1)
    assert_eq "newest window cwd" "${SCRATCH:A}/term2" "${newest#* }"
}

# An interactive shell outside tmux must hand off to tmux-launch. A stand-in
# tmux-launch on PATH records that it ran; tmux itself is never reached.
test_zshrc_hands_off_to_tmux_launch() {
    bold "\nTest: dot.zshrc execs tmux-launch for an interactive shell outside tmux\n"

    local stage="${SCRATCH}/zdot" bindir="${SCRATCH}/fakebin"
    mkdir -p "${stage}" "${bindir}"
    cp "${DOT_ZSHRC}" "${stage}/.zshrc"
    {
        print '#!/bin/sh'
        print "echo launched > '${SCRATCH}/launched'"
    } > "${bindir}/tmux-launch"
    chmod +x "${bindir}/tmux-launch"

    env -i HOME="${SCRATCH}" ZDOTDIR="${stage}" TERM=dumb \
        PATH="${bindir}:/usr/bin:/bin" /bin/zsh -ic 'true' </dev/null >/dev/null 2>&1 || true

    assert_eq "tmux-launch ran" launched "$(cat "${SCRATCH}/launched" 2>/dev/null || true)"
}

# --- Main ---

main() {
    bold "=== tmux-launch smoke test ===\n\n"

    setup
    test_first_terminal_creates_the_session
    test_second_terminal_adds_a_window_not_a_session
    test_new_window_starts_in_the_terminals_directory
    test_zshrc_hands_off_to_tmux_launch

    print ""
    bold "=== Results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    if (( TESTS_FAILED > 0 )); then
        red ", ${TESTS_FAILED} failed"
    fi
    print " ==="

    (( TESTS_FAILED == 0 ))
}

main "$@"
