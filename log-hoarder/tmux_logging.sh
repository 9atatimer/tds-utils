#!/bin/zsh
# tmux_logging.sh — start pipe-pane logging for the current tmux pane
#
# Invoked by tmux hooks on session-created, after-new-window, after-split-window.
# Writes to $TDS_LOG_DIR/active/$SESSION/@WINDOW/%PANE/HHMMSS.log
#
# The path keys on tmux's IMMUTABLE ids ($N/@N/%N), never on the session name:
# a `tmux rename-session` would otherwise leave this pipe writing under a name
# the shepherd's sweep believes is dead (issue #307). The human-readable name
# is recorded alongside, in active/$SESSION/name.txt.
#
# Log path convention is shared with tmux_shepherd.sh — do not change independently.

set -euo pipefail
umask 077

# --- Diagnostics ---

DIAG_HOOK="logging"

diag_log() {
    local msg="$1"
    local logdir="${TDS_LOG_DIR:-$HOME}"
    print "$(date '+%Y-%m-%d %H:%M:%S') [${DIAG_HOOK}] ${msg}" >> "${logdir}/log-hoarder.${DIAG_HOOK}.log"
}

# --- Action functions ---

warn_no_log_dir() {
    # Called from a tmux hook — no TTY available, so no banner.
    # Condition is already captured in the diag log.
    :;
}

check_ansifilter() {
    command -v ansifilter >/dev/null 2>&1
}

# The three ids of the pane this hook fired for, plus the session's creation
# stamp, space-separated. None of them can contain a space, so the caller may
# split on it.
pane_ids() {
    tmux display-message -p '#{session_id} #{window_id} #{pane_id} #{session_created}'
}

session_name() {
    tmux display-message -p '#S'
}

# A tmux id is unique only within one running server: after a restart, $0/@0/%0
# are handed out again, so a tree left behind in active/ by a dead server would
# be adopted by a brand new session -- its logs interleaved, and its archive
# destination already occupied. The session's creation stamp settles ownership.
# A tree stamped by a different session is set aside under a key no live
# session can match, which is exactly what the shepherd's sweep archives.
claim_session_dir() {
    local sessiondir="$1" created="$2"
    local stampfile="${sessiondir}/created.txt"
    local previous aside

    if [[ -f "${stampfile}" ]]; then
        previous=$(<"${stampfile}")
        if [[ "${previous}" != "${created}" ]]; then
            aside="${sessiondir}-${previous}"
            [[ -e "${aside}" ]] && aside="${aside}-${created}"
            mv "${sessiondir}" "${aside}"
            diag_log "session id reused; set aside: ${sessiondir} -> ${aside}"
        fi
    fi

    mkdir -p "${sessiondir}"
    print -r -- "${created}" > "${stampfile}"
}

# The name is display data, not a key: it is recorded next to the logs so a
# human (or the indexer) can still say which session a directory belonged to.
record_session_name() {
    local sessiondir="$1" name="$2"
    mkdir -p "${sessiondir}"
    print -r -- "${name}" > "${sessiondir}/name.txt"
}

build_log_path() {
    local session_id="$1" window_id="$2" pane_id="$3"
    local stamp
    stamp=$(date '+%H%M%S')

    local logdir="${TDS_LOG_DIR}/active/${session_id}/${window_id}/${pane_id}"
    mkdir -p "${logdir}"
    echo "${logdir}/${stamp}.log"
}

# tmux runs the pipe command through strftime(3) before the shell sees it, and
# every pane id carries a '%'. Undoubled, '%0' is consumed as an unknown
# conversion and the log lands one directory up from its pane.
escape_strftime() {
    print -r -- "${1//\%/%%}"
}

start_pipe_pane() {
    local pane_id="$1" logpath="$2"
    # The path is single-quoted for the shell tmux runs the pipe command in:
    # a session id begins with '$' and would otherwise be expanded away.
    local quoted
    quoted=$(escape_strftime "${logpath}")

    if check_ansifilter; then
        tmux pipe-pane -o -t "${pane_id}" "ansifilter >> '${quoted}'"
        diag_log "pipe opened (ansifilter): ${logpath}"
    else
        echo "# log-hoarder: ansifilter not found; log contains raw ANSI sequences" >> "${logpath}"
        tmux pipe-pane -o -t "${pane_id}" "cat >> '${quoted}'"
        diag_log "pipe opened (raw, ansifilter missing): ${logpath}"
    fi
}

# --- Flow functions ---

run_logging() {
    if [[ -z "${TDS_LOG_DIR:-}" ]]; then
        diag_log "TDS_LOG_DIR not set — logging suppressed"
        warn_no_log_dir
        return 0
    fi

    local ids
    ids=(${=$(pane_ids)})
    local session_id="${ids[1]}" window_id="${ids[2]}" pane_id="${ids[3]}"
    local created="${ids[4]}"

    claim_session_dir "${TDS_LOG_DIR}/active/${session_id}" "${created}"
    record_session_name "${TDS_LOG_DIR}/active/${session_id}" "$(session_name)"

    local logpath
    logpath=$(build_log_path "${session_id}" "${window_id}" "${pane_id}")
    start_pipe_pane "${pane_id}" "${logpath}"
}

# --- Main ---

main() {
    diag_log "invoked (pid=$$)"
    run_logging
}

main "$@"
