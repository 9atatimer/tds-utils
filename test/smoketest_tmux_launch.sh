#!/bin/zsh
# smoketest_tmux_launch.sh -- one terminal, one window in ONE shared tmux session
#
# Runs bin/tmux-launch against a PRIVATE tmux server (`tmux -L <socket>`), with
# the attach step skipped (TDS_TMUX_NO_ATTACH=1): attaching needs a terminal,
# and everything before it is where the behavior lives.  Requires: tmux.
#
# Covered: first terminal creates the session, later terminals add a window to
# it instead of creating another session, and a new window starts in the
# directory the terminal was opened in; with no terminal, tmux-launch opens
# no window.  Also the dot.zshrc wiring: a terminal's shell outside tmux hands
# off to tmux-launch, and a shell with no terminal or a -c command does not
# (issue #427 -- GUI environment probes left stray windows), nor does a
# Claude desktop Terminal-panel tab (issue #498).  Requires script(1) for the
# pty cases.
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

# Run a command on a pseudo-terminal, the way a terminal emulator starts a
# shell. BSD script(1) takes the command as argv; util-linux takes it as -c.
in_pty() {
    if [[ "$(uname -s)" == Darwin ]]; then
        script -q /dev/null "$@"
    else
        script -qec "${(j: :)${(q)@}}" /dev/null
    fi
}

# Stage dot.zshrc with a stand-in tmux-launch on PATH that records that it
# ran; tmux itself is never reached. Prints the ZDOTDIR and fake bin dir.
stage_zshrc() {
    local stage="${SCRATCH}/zdot" bindir="${SCRATCH}/fakebin"
    rm -rf "${stage}" "${bindir}" "${SCRATCH}/launched"
    mkdir -p "${stage}" "${bindir}"
    cp "${DOT_ZSHRC}" "${stage}/.zshrc"
    {
        print '#!/bin/sh'
        print "echo launched > '${SCRATCH}/launched'"
    } > "${bindir}/tmux-launch"
    chmod +x "${bindir}/tmux-launch"
    print -r -- "${stage} ${bindir}"
}

# A shell started with only the staged .zshrc and the stand-in on PATH.
staged_zsh() {
    local stage="$1" bindir="$2"
    shift 2
    env -i HOME="${SCRATCH}" ZDOTDIR="${stage}" TERM=dumb \
        PATH="${bindir}:/usr/bin:/bin" /bin/zsh "$@"
}

launched() { cat "${SCRATCH}/launched" 2>/dev/null || print -r -- not-launched; }

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
trap cleanup EXIT INT TERM HUP

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

# A terminal emulator starts an interactive shell on a pty; outside tmux it
# must hand off to tmux-launch.
test_zshrc_hands_off_to_tmux_launch() {
    bold "\nTest: dot.zshrc execs tmux-launch for a terminal's shell outside tmux\n"

    local dirs
    dirs=(${(z)"$(stage_zshrc)"})
    in_pty env -i HOME="${SCRATCH}" ZDOTDIR="${dirs[1]}" TERM=dumb \
        PATH="${dirs[2]}:/usr/bin:/bin" /bin/zsh -i </dev/null >/dev/null 2>&1 || true

    assert_eq "tmux-launch ran" launched "$(launched)"
}

# Issue #427. A GUI app (Claude desktop, an editor) reads the user's
# environment by running an interactive login shell with no terminal. Handed
# to tmux-launch, that probe left a stray window in session main and never
# returned its environment.
test_zshrc_env_probe_without_terminal_stays_out_of_tmux() {
    bold "\nTest: an interactive shell with no terminal runs its command, not tmux\n"

    local dirs out
    dirs=(${(z)"$(stage_zshrc)"})
    out=$(staged_zsh "${dirs[1]}" "${dirs[2]}" -lic 'print probe-ok' </dev/null 2>/dev/null || true)

    assert_eq "tmux-launch did not run" not-launched "$(launched)"
    assert_eq "the probe's command ran" probe-ok "${out}"
}

# A shell given a command (-c) exists to run it, terminal or not. Some env
# probes run on a pty, and `zsh -ic cmd` typed at a terminal means cmd.
test_zshrc_command_shell_on_terminal_stays_out_of_tmux() {
    bold "\nTest: zsh -ic on a terminal runs its command, not tmux\n"

    local dirs out
    dirs=(${(z)"$(stage_zshrc)"})
    out=$(in_pty env -i HOME="${SCRATCH}" ZDOTDIR="${dirs[1]}" TERM=dumb \
        PATH="${dirs[2]}:/usr/bin:/bin" /bin/zsh -ic 'print cmd-ok' </dev/null 2>/dev/null || true)

    assert_eq "tmux-launch did not run" not-launched "$(launched)"
    assert_eq "the command ran" 1 "$(print -r -- "${out}" | grep -c cmd-ok || true)"
}

# Issue #498. A tab in the Claude desktop app's Terminal panel is an
# interactive shell on a pty with no -c, so it passes every check above. Handed
# to tmux-launch it joined session main, switched the human's terminals onto
# its window, and left that window behind when the tab closed.
test_zshrc_claude_desktop_terminal_stays_out_of_tmux() {
    bold "\nTest: a Claude desktop Terminal-panel shell stays out of tmux\n"

    local dirs
    dirs=(${(z)"$(stage_zshrc)"})
    in_pty env -i HOME="${SCRATCH}" ZDOTDIR="${dirs[1]}" TERM=dumb \
        TERM_PROGRAM=claude-desktop \
        PATH="${dirs[2]}:/usr/bin:/bin" /bin/zsh -i </dev/null >/dev/null 2>&1 || true

    assert_eq "tmux-launch did not run" not-launched "$(launched)"
}

# The accept side of the terminal guard: on a terminal, tmux-launch still
# opens a window and attaches. A client-attached hook records the attach and
# detaches at once, so the attach returns instead of holding the test.
test_launch_on_terminal_adds_a_window_and_attaches() {
    bold "\nTest: tmux-launch on a terminal adds a window and attaches\n"

    local before
    before=$(window_count)
    tm set-hook -g client-attached "run-shell \"touch '${SCRATCH}/attached'\" ; detach-client"
    ( cd "${SCRATCH}/term1" && in_pty env TDS_TMUX_SOCKET="${SOCKET}" \
        /bin/zsh -f "${LAUNCH_SH}" </dev/null >/dev/null 2>&1 ) || true
    tm set-hook -gu client-attached

    assert_eq "one more window" "$(( before + 1 ))" "$(window_count)"
    assert_eq "a client attached" yes "$([[ -e "${SCRATCH}/attached" ]] && print yes || print no)"
}

# A window is only worth creating if a terminal will attach to it. Whatever
# calls tmux-launch without one, it must not leave a window behind (#427).
test_launch_without_terminal_adds_no_window() {
    bold "\nTest: tmux-launch with no terminal adds no window and says why\n"

    local before rc=0 err
    before=$(window_count)
    err=$( ( cd "${SCRATCH}/term1" && TDS_TMUX_SOCKET="${SOCKET}" \
        /bin/zsh -f "${LAUNCH_SH}" </dev/null >/dev/null ) 2>&1 ) || rc=$?

    assert_eq "window count unchanged" "${before}" "$(window_count)"
    assert_eq "it exits non-zero" 1 "$(( rc != 0 ))"
    assert_eq "it names the missing terminal" 1 "$(print -r -- "${err}" | grep -c 'no terminal' || true)"
}

# --- Main ---

main() {
    bold "=== tmux-launch smoke test ===\n\n"

    setup
    test_first_terminal_creates_the_session
    test_second_terminal_adds_a_window_not_a_session
    test_new_window_starts_in_the_terminals_directory
    test_launch_on_terminal_adds_a_window_and_attaches
    test_launch_without_terminal_adds_no_window
    test_zshrc_hands_off_to_tmux_launch
    test_zshrc_env_probe_without_terminal_stays_out_of_tmux
    test_zshrc_command_shell_on_terminal_stays_out_of_tmux
    test_zshrc_claude_desktop_terminal_stays_out_of_tmux

    print ""
    bold "=== Results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    if (( TESTS_FAILED > 0 )); then
        red ", ${TESTS_FAILED} failed"
    fi
    print " ==="

    (( TESTS_FAILED == 0 ))
}

main "$@"
