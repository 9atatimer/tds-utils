#!/bin/zsh
# tmux_logging.sh — start pipe-pane logging for the current tmux pane
#
# Invoked by tmux hooks on session-created, after-new-window, after-split-window.
# Writes to $TDS_LOG_DIR/active/SESSION/WINDOW/PANE/HHMMSS.log
#
# Log path convention is shared with tmux_shepherd.sh — do not change independently.

set -euo pipefail

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

build_log_path() {
    local session window_idx pane_idx stamp
    session=$(tmux display-message -p '#S')
    window_idx=$(tmux display-message -p '#I')
    pane_idx=$(tmux display-message -p '#P')
    stamp=$(date '+%H%M%S')

    local logdir="${TDS_LOG_DIR}/active/${session}/${window_idx}/${pane_idx}"
    mkdir -p "${logdir}"
    echo "${logdir}/${stamp}.log"
}

start_pipe_pane() {
    local logpath="$1"
    if check_ansifilter; then
        tmux pipe-pane -o "ansifilter >> '${logpath}'"
        diag_log "pipe opened (ansifilter): ${logpath}"
    else
        echo "# log-hoarder: ansifilter not found; log contains raw ANSI sequences" >> "${logpath}"
        tmux pipe-pane -o "cat >> '${logpath}'"
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

    local logpath
    logpath=$(build_log_path)
    start_pipe_pane "${logpath}"
}

# --- Main ---

main() {
    diag_log "invoked (pid=$$)"
    run_logging
}

main "$@"
