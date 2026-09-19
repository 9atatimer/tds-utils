#!/bin/zsh
# smoketest_log_hoarder.sh — end-to-end smoke test for log-hoarder
#
# Runs against a PRIVATE tmux server (`tmux -L <socket>`) loaded from THIS
# checkout's log-hoarder/tmux.conf, so the hooks under test are the ones in
# this worktree and the user's own sessions are never touched.  Requires: tmux.
#
# Covered: the directory key (immutable tmux ids, issue #307), name.txt,
# survival of a live rename, shepherd archive/sweep behaviour, the legacy
# name-keyed fallback, and the "suppressed" code path.
#
# Usage: ./test/smoketest_log_hoarder.sh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
LOGGING_SH="${REPO_DIR}/bin/tmux_logging.sh"
SHEPHERD_SH="${REPO_DIR}/bin/tmux_shepherd.sh"
REPO_TMUX_CONF="${REPO_DIR}/log-hoarder/tmux.conf"
SOCKET="log-hoarder-smoke-$$"

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
TEST_TDS_LOG_DIR=""
TEST_TMUX=""

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

# --- tmux helpers (private server only) ---

tm() { tmux -L "${SOCKET}" "$@"; }

# Run a log-hoarder script outside the server, pointed at the private server.
run_shepherd() {
    TMUX="${TEST_TMUX}" TDS_LOG_DIR="${TDS_LOG_DIR}" /bin/zsh -f "${SHEPHERD_SH}" "$@"
}

# Immutable-id pane directory for a session's first pane.
pane_dir_of() {
    local target="$1" ids
    ids=(${=$(tm display-message -p -t "${target}" '#{session_id} #{window_id} #{pane_id}')})
    print "${TDS_LOG_DIR}/active/${ids[1]}/${ids[2]}/${ids[3]}"
}

session_id_of() { tm display-message -p -t "$1" '#{session_id}'; }

# Poll a condition for up to <seconds>; pipe-pane output is asynchronous.
wait_for() {
    local deadline=$(( SECONDS + $1 )) cond="$2"
    while (( SECONDS < deadline )); do
        eval "${cond}" && return 0
        sleep 0.2
    done
    return 1
}

create_logged_session() {
    local name="$1"
    tm new-session -d -s "${name}"
    # The session-created hook from tmux.conf fires automatically.
    sleep 1
}

setup() {
    TEST_TDS_LOG_DIR=$(mktemp -d "${TMPDIR:-/tmp}/log-hoarder-test.XXXXXX")
    export TDS_LOG_DIR="${TEST_TDS_LOG_DIR}"
    mkdir -p "${TDS_LOG_DIR}/active" "${TDS_LOG_DIR}/archived"

    # A wrapper conf: this checkout's tmux.conf, with the hook scripts
    # repointed at this checkout's bin/ instead of the machine's.
    local conf="${TEST_TDS_LOG_DIR}/tmux.conf"
    {
        print "source-file ${REPO_TMUX_CONF}"
        print "set -g @log_hoarder_bin \"${REPO_DIR}/bin\""
    } > "${conf}"

    # TDS_LOG_DIR is exported, so the server (and every run-shell child)
    # inherits the test value.
    tm -f "${conf}" new-session -d -s bootstrap
    tm set-environment -g TDS_LOG_DIR "${TDS_LOG_DIR}"
    TEST_TMUX="$(tm display-message -p '#{socket_path}'),$(tm display-message -p '#{pid}'),0"
}

cleanup() {
    local sock
    for sock in "${SOCKET}" "${SOCKET}-b" "${SOCKET}-c"; do
        tmux -L "${sock}" kill-server 2>/dev/null || true
    done
    if [[ -n "${TEST_TDS_LOG_DIR}" ]]; then
        rm -rf "${TEST_TDS_LOG_DIR}"
    fi
}
trap cleanup EXIT

# --- Tests ---

test_logging_keys_on_immutable_ids() {
    bold "Test: logging keys the pane dir on immutable tmux ids\n"

    create_logged_session "smoke-log"

    local panedir
    panedir=$(pane_dir_of "smoke-log")
    assert "id-keyed pane dir exists: ${panedir#${TDS_LOG_DIR}/}" "[[ -d '${panedir}' ]]"
    assert "no name-keyed dir"  "[[ ! -d '${TDS_LOG_DIR}/active/smoke-log' ]]"

    local diag="${TDS_LOG_DIR}/log-hoarder.logging.log"
    assert "diag log exists"             "[[ -f '${diag}' ]]"
    assert "diag log shows pipe opened"  "grep -q 'pipe opened' '${diag}'"
}

test_session_name_recorded_alongside() {
    bold "\nTest: the human-readable session name is recorded, not used as the key\n"

    local sid
    sid=$(session_id_of "smoke-log")
    local namefile="${TDS_LOG_DIR}/active/${sid}/name.txt"

    assert "name.txt exists" "[[ -f '${namefile}' ]]"
    assert_eq "name.txt holds the session name" "smoke-log" "$(cat "${namefile}" 2>/dev/null)"
}

test_rename_does_not_strand_the_pipe() {
    bold "\nTest: renaming a live session strands neither the pipe nor the dir (#307)\n"

    create_logged_session "smoke-rename"
    local sid panedir
    sid=$(session_id_of "smoke-rename")
    panedir=$(pane_dir_of "smoke-rename")
    assert "pane dir exists before rename" "[[ -d '${panedir}' ]]"

    # tmux runs the pipe command through strftime(3), which eats an undoubled
    # '%N' pane id and drops the log one directory up. The file is created by
    # the '>>' redirection, so its presence is checkable without waiting on
    # (block-buffered) pane output.
    wait_for 5 "[[ -n \$(print -rl -- '${panedir}'/*.log(N)) ]]" || true
    assert "the log file lands in the PANE dir" \
        "[[ -n \$(print -rl -- '${panedir}'/*.log(N)) ]]"

    tm rename-session -t "smoke-rename" "smoke-renamed"
    run_shepherd

    assert "pipe still writes to the same single file" \
        "(( \$(print -rl -- '${panedir}'/*.log(N) | grep -c .) == 1 ))"
    assert "pane dir survives the rename"    "[[ -d '${panedir}' ]]"
    assert "nothing was archived"            "[[ ! -d '${TDS_LOG_DIR}/archived/${sid}' ]]"
    assert "pipe is still open"              "[[ \$(tm display-message -p -t 'smoke-renamed' '#{pane_pipe}') == 1 ]]"
    assert_eq "name.txt follows the rename" "smoke-renamed" \
        "$(cat "${TDS_LOG_DIR}/active/${sid}/name.txt" 2>/dev/null)"
}

test_shepherd_skips_alive_session() {
    bold "\nTest: shepherd refuses to archive a live session\n"

    create_logged_session "smoke-alive"
    local ids panedir
    ids=(${=$(tm display-message -p -t 'smoke-alive' '#{session_id} #{window_id} #{pane_id}')})
    panedir="${TDS_LOG_DIR}/active/${ids[1]}/${ids[2]}/${ids[3]}"
    assert "pane dir exists before shepherd" "[[ -d '${panedir}' ]]"

    run_shepherd "${ids[1]}" "${ids[2]}" "${ids[3]}"

    assert "pane dir still exists (not archived)" "[[ -d '${panedir}' ]]"
    assert "archived dir does NOT exist" "[[ ! -d '${TDS_LOG_DIR}/archived/${ids[1]}' ]]"

    local diag="${TDS_LOG_DIR}/log-hoarder.shepherd.hook.log"
    assert "diag shows 'still alive' skip" "grep -q 'still alive' '${diag}'"
}

test_shepherd_archives_dead_session() {
    bold "\nTest: shepherd archives a dead session by id, carrying the name\n"

    create_logged_session "smoke-dead"
    local ids panedir
    ids=(${=$(tm display-message -p -t 'smoke-dead' '#{session_id} #{window_id} #{pane_id}')})
    panedir="${TDS_LOG_DIR}/active/${ids[1]}/${ids[2]}/${ids[3]}"
    assert "pane dir exists before kill" "[[ -d '${panedir}' ]]"

    tm kill-session -t "smoke-dead"
    run_shepherd "${ids[1]}" "${ids[2]}" "${ids[3]}"

    local archived="${TDS_LOG_DIR}/archived/${ids[1]}/${ids[2]}/${ids[3]}"
    assert "archived pane dir exists"   "[[ -d '${archived}' ]]"
    assert "active pane dir is gone"    "[[ ! -d '${panedir}' ]]"
    assert "active session dir is gone" "[[ ! -d '${TDS_LOG_DIR}/active/${ids[1]}' ]]"
    assert_eq "name.txt carried to archived" "smoke-dead" \
        "$(cat "${TDS_LOG_DIR}/archived/${ids[1]}/name.txt" 2>/dev/null)"
}

test_legacy_name_keyed_dir_is_swept_by_name() {
    bold "\nTest: pre-#307 name-keyed dirs are still judged by name\n"

    create_logged_session "smoke-legacy"

    # Simulate a dir written by the pre-#307 code: keyed on the session name.
    local live="${TDS_LOG_DIR}/active/smoke-legacy/0/0"
    local dead="${TDS_LOG_DIR}/active/smoke-gone/0/0"
    mkdir -p "${live}" "${dead}"

    run_shepherd

    assert "legacy dir of a LIVE session is left alone" "[[ -d '${live}' ]]"
    assert "legacy dir of a DEAD session is archived" \
        "[[ -d '${TDS_LOG_DIR}/archived/smoke-gone/0/0' ]]"
}

test_reused_session_id_does_not_adopt_a_stale_tree() {
    bold "\nTest: a reused session id does not adopt the dead session's tree\n"

    create_logged_session "smoke-reuse"
    local sid panedir
    sid=$(session_id_of "smoke-reuse")
    panedir=$(pane_dir_of "smoke-reuse")

    # tmux ids restart at $0/@0/%0 on every server restart, so a tree left in
    # active/ by a dead server can be re-keyed by a brand new session. Forge
    # that: an older creation stamp plus a log the new session must not touch.
    print "1" > "${TDS_LOG_DIR}/active/${sid}/created.txt"
    print "dead session output" > "${panedir}/stale.log"

    # Opening another pane on the same session re-runs the logging hook.
    tm new-window -t "smoke-reuse"
    sleep 1

    # [[ -f ]] does not glob, and `print -rl` emits a blank line for no
    # matches -- -rn gives genuinely empty output.
    assert "the dead session's tree was set aside" \
        "[[ -n \$(print -rn -- '${TDS_LOG_DIR}/active/${sid}-1'/*/*/stale.log(N)) ]]"
    assert "the live tree does not carry the dead session's log" \
        "[[ ! -e '${panedir}/stale.log' ]]"
    assert "the live tree is re-stamped" \
        "[[ \$(cat '${TDS_LOG_DIR}/active/${sid}/created.txt') != 1 ]]"

    run_shepherd
    assert "the set-aside tree archives on the next sweep" \
        "[[ -n \$(print -rn -- '${TDS_LOG_DIR}/archived/${sid}-1'/*/*/stale.log(N)) ]]"
}

test_archive_separates_generations_that_reuse_an_id() {
    bold "\nTest: an archived id already taken by an earlier session is not merged into\n"

    create_logged_session "smoke-collide"
    local ids panedir
    ids=(${=$(tm display-message -p -t 'smoke-collide' '#{session_id} #{window_id} #{pane_id}')})
    panedir="${TDS_LOG_DIR}/active/${ids[1]}/${ids[2]}/${ids[3]}"

    # An earlier session, same ids, already archived -- what a server restart
    # produces. Plain `mv` would move the live pane INSIDE it, and a shared
    # name.txt would be overwritten by whichever session archived last.
    local earlier="${TDS_LOG_DIR}/archived/${ids[1]}"
    mkdir -p "${earlier}/${ids[2]}/${ids[3]}"
    print "earlier session" > "${earlier}/${ids[2]}/${ids[3]}/old.log"
    print "earlier-name"    > "${earlier}/name.txt"
    print "1"               > "${earlier}/created.txt"
    print "this session"    > "${panedir}/new.log"

    tm kill-session -t "smoke-collide"
    run_shepherd "${ids[1]}" "${ids[2]}" "${ids[3]}"

    local later="${earlier}.1"
    assert "the earlier archive is untouched" \
        "[[ -f '${earlier}/${ids[2]}/${ids[3]}/old.log' ]]"
    assert "nothing was nested inside it" \
        "[[ ! -e '${earlier}/${ids[2]}/${ids[3]}/${ids[3]}' ]]"
    assert "this session archived under its own root" \
        "[[ -f '${later}/${ids[2]}/${ids[3]}/new.log' ]]"
    assert_eq "the earlier archive keeps its name" "earlier-name" \
        "$(cat "${earlier}/name.txt" 2>/dev/null)"
    assert_eq "this session's archive carries ITS name" "smoke-collide" \
        "$(cat "${later}/name.txt" 2>/dev/null)"
}

test_ownership_stamp_is_server_unique() {
    bold "\nTest: the ownership stamp is not just a wall-clock second\n"

    local sid stamp
    sid=$(session_id_of "smoke-log")
    stamp=$(cat "${TDS_LOG_DIR}/active/${sid}/created.txt")

    # tmux reports session_created at second granularity, so on its own it
    # cannot tell two servers' $0 apart: a restart inside one second would
    # mint the same value. The server's start time and pid pin it down.
    assert "stamp is more than #{session_created}" \
        "[[ '${stamp}' != \$(tm display-message -p -t 'smoke-log' '#{session_created}') ]]"
    assert "stamp carries the server start time" \
        "[[ '${stamp}' == *\$(tm display-message -p '#{start_time}')* ]]"
    assert "stamp carries the server pid" \
        "[[ '${stamp}' == *\$(tm display-message -p '#{pid}')* ]]"
}

test_a_second_server_does_not_adopt_the_first_servers_tree() {
    bold "\nTest: a fresh server's \$0 does not adopt a dead server's \$0 tree\n"

    # Both servers share one TDS_LOG_DIR and both hand out $0/@0/%0 -- the
    # real shape of a restart, played out end to end rather than forged.
    local sock2="${SOCKET}-b"
    local conf="${TEST_TDS_LOG_DIR}/tmux.conf"

    tmux -L "${sock2}" -f "${conf}" new-session -d -s server-b
    sleep 1
    local sid2 panedir2 ids2
    ids2=(${=$(tmux -L "${sock2}" display-message -p -t 'server-b' '#{session_id} #{window_id} #{pane_id}')})
    sid2="${ids2[1]}"
    panedir2="${TDS_LOG_DIR}/active/${ids2[1]}/${ids2[2]}/${ids2[3]}"

    print "server B output" > "${panedir2}/b.log"
    tmux -L "${sock2}" kill-server 2>/dev/null || true

    # A third server, same id space, same log dir.
    local sock3="${SOCKET}-c"
    tmux -L "${sock3}" -f "${conf}" new-session -d -s server-c
    sleep 1
    local ids3 panedir3
    ids3=(${=$(tmux -L "${sock3}" display-message -p -t 'server-c' '#{session_id} #{window_id} #{pane_id}')})
    panedir3="${TDS_LOG_DIR}/active/${ids3[1]}/${ids3[2]}/${ids3[3]}"

    assert_eq "the two servers really did reuse the id" "${sid2}" "${ids3[1]}"
    assert "server C did not inherit server B's log" "[[ ! -e '${panedir3}/b.log' ]]"
    assert "server B's tree was set aside intact" \
        "[[ -n \$(print -rn -- '${TDS_LOG_DIR}/active/${sid2}'-*/*/*/b.log(N)) ]]"

    tmux -L "${sock3}" kill-server 2>/dev/null || true
}

test_unstamped_tree_is_not_adopted() {
    bold "\nTest: an unstamped (pre-#307) tree at an id path is not adopted\n"

    create_logged_session "smoke-unstamped"
    local sid panedir
    sid=$(session_id_of "smoke-unstamped")
    panedir=$(pane_dir_of "smoke-unstamped")

    # A pre-#307 tree is keyed on the session NAME, and a name can look exactly
    # like an id -- so an unstamped tree here belongs to something else.
    rm -f "${TDS_LOG_DIR}/active/${sid}/created.txt"
    print "someone else's output" > "${panedir}/legacy.log"

    tm new-window -t "smoke-unstamped"
    sleep 1

    assert "the unstamped tree was set aside" \
        "[[ -n \$(print -rn -- '${TDS_LOG_DIR}/active/${sid}-unstamped'/*/*/legacy.log(N)) ]]"
    assert "the live tree does not carry its log" "[[ ! -e '${panedir}/legacy.log' ]]"
    assert "the live tree is stamped" \
        "[[ -f '${TDS_LOG_DIR}/active/${sid}/created.txt' ]]"
}

test_id_shaped_session_name_is_not_read_as_an_id() {
    bold "\nTest: a legacy dir named like a session id is still judged by name\n"

    # tmux accepts '$9999' as a session NAME, and no session will hold it as
    # an id here -- so a key's shape cannot say which kind of key it is.
    tm new-session -d -s '$9999'
    sleep 1
    assert "precondition: no live session holds that id" \
        "! tm list-sessions -F '#{session_id}' | grep -qxF -- '\$9999'"

    local legacy="${TDS_LOG_DIR}/active/"'$9999'"/0/0"
    mkdir -p "${legacy}"

    run_shepherd

    assert "legacy dir of a live, id-shaped NAME survives" "[[ -d '${legacy}' ]]"
}

test_cron_brands_unbranded_pane_dirs() {
    bold "\nTest: the cron sweep hands unbranded pane dirs to the brander\n"

    local panedir="${TDS_LOG_DIR}/archived/"'$99'"/@0/%0"
    mkdir -p "${panedir}"
    print "some terminal output" > "${panedir}/000000.log"

    local fake="${TEST_TDS_LOG_DIR}/fake_brander"
    cat > "${fake}" <<'BRANDER'
#!/bin/zsh
print "fake-slug" > "$1/slug.txt"
BRANDER

    TMUX="${TEST_TMUX}" TDS_LOG_DIR="${TDS_LOG_DIR}" LOG_BRANDER="${fake}" \
        /bin/zsh -f "${SHEPHERD_SH}"

    assert "brander ran on the unbranded pane dir" "[[ -f '${panedir}/slug.txt' ]]"
    assert_eq "slug.txt holds what the brander wrote" "fake-slug" \
        "$(cat "${panedir}/slug.txt" 2>/dev/null)"
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
    test_logging_keys_on_immutable_ids
    test_session_name_recorded_alongside
    test_rename_does_not_strand_the_pipe
    test_shepherd_skips_alive_session
    test_shepherd_archives_dead_session
    test_legacy_name_keyed_dir_is_swept_by_name
    test_reused_session_id_does_not_adopt_a_stale_tree
    test_archive_separates_generations_that_reuse_an_id
    test_ownership_stamp_is_server_unique
    test_a_second_server_does_not_adopt_the_first_servers_tree
    test_unstamped_tree_is_not_adopted
    test_id_shaped_session_name_is_not_read_as_an_id
    test_cron_brands_unbranded_pane_dirs
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
