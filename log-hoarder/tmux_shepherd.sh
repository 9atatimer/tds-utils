#!/bin/zsh
# tmux_shepherd.sh — log lifecycle manager for log-hoarder
#
# Invoked two ways:
#
#   1. tmux pane-exited hook — args: SESSION WINDOW PANE
#      - Moves that pane's log dir from active/ to archived/
#      - Sweeps active/ for orphaned pane dirs (sessions no longer alive)
#
#   2. cron (no args) — straggler sweep
#      - Sweeps archived/ for unprocessed pane dirs (no slug.txt present)
#      - Delegates to ~/bin/log_brander for LLM slug generation
#
# Directory convention (shared with tmux_logging.sh):
#   active/SESSION/WINDOW/PANE/HHMMSS.log
#   archived/SESSION/WINDOW/PANE/HHMMSS.log     (moved, not yet branded)
#   archived/SESSION/WINDOW/PANE/slug.txt        (written by log_brander)

set -euo pipefail
umask 077

# --- Diagnostics ---
# DIAG_HOOK is set in main once invocation mode is known.
# diag_log is defined here but safe to call before DIAG_HOOK is set
# only after main() resolves it.

DIAG_HOOK="shepherd.unknown"
DIAG_LOG=""

diag_log() {
    local msg="$1"
    # DIAG_LOG resolved after mode detection; fallback to HOME if still empty
    local logfile="${DIAG_LOG:-$HOME/log-hoarder.shepherd.log}"
    print "$(date '+%Y-%m-%d %H:%M:%S') [${DIAG_HOOK}] ${msg}" >> "${logfile}"
}

resolve_diag_log() {
    DIAG_LOG="${${TDS_LOG_DIR:-$HOME}}/log-hoarder.${DIAG_HOOK}.log"
}

# --- Action functions ---

warn_no_log_dir() {
    print -u2 "\033[1;33m"
    print -u2 "╔══════════════════════════════════════════════════════════╗"
    print -u2 "║  log-hoarder: TDS_LOG_DIR is not set.                   ║"
    print -u2 "║  tmux_shepherd cannot run without it.                   ║"
    print -u2 "╚══════════════════════════════════════════════════════════╝"
    print -u2 "\033[0m"
}

active_dir()   { echo "${TDS_LOG_DIR}/active"; }
archived_dir() { echo "${TDS_LOG_DIR}/archived"; }

# Move a pane directory from active/ to archived/, preserving session/window/pane hierarchy.
archive_pane_dir() {
    local session="$1" window="$2" pane="$3"
    local src="$(active_dir)/${session}/${window}/${pane}"
    local dst="$(archived_dir)/${session}/${window}/${pane}"

    [[ -d "${src}" ]] || return 0

    mkdir -p "$(dirname "${dst}")"
    mv "${src}" "${dst}"
    diag_log "archived: ${src} → ${dst}"
}

# Returns true if the named tmux session is currently alive.
session_alive() {
    local session="$1"
    tmux list-sessions -F '#S' 2>/dev/null | grep -qx "${session}"
}

# Returns true if a pane dir in archived/ has not yet been branded.
# Heuristic: no slug.txt present.
is_unbranded() {
    local panedir="$1"
    [[ ! -f "${panedir}/slug.txt" ]]
}

# Delegate branding to log_brander — it owns model selection, sampling, slug writing.
brand_pane_dir() {
    local panedir="$1"
    diag_log "branding: ${panedir}"
    ~/bin/log_brander "${panedir}" || true
}

# --- Flow functions ---

# Called from tmux hook: archive this pane's dir, then sweep for orphans.
# Trust but verify: tmux format variables may resolve to the wrong session
# during teardown, so confirm the session is actually dead before archiving.
run_hook_mode() {
    local session="$1" window="$2" pane="$3"

    diag_log "hook invoked: session=${session} window=${window} pane=${pane}"
    if session_alive "${session}"; then
        diag_log "session ${session} still alive — skipping direct archive, deferring to orphan sweep"
    else
        archive_pane_dir "${session}" "${window}" "${pane}"
    fi
    sweep_orphans
    diag_log "hook complete"
}

# Called from cron: sweep archived/ for unbranded pane dirs and brand them.
run_cron_mode() {
    local arch
    arch=$(archived_dir)
    diag_log "cron sweep started: ${arch}"

    sweep_orphans

    local count=0
    for panedir in "${arch}"/*/*/*(N/); do
        if is_unbranded "${panedir}"; then
            brand_pane_dir "${panedir}"
            (( count++ )) || true
        fi
    done

    diag_log "cron sweep complete: ${count} pane(s) branded"
}

# Sweep active/ for session dirs whose session is no longer alive.
sweep_orphans() {
    local act
    act=$(active_dir)

    local session
    for sessiondir in "${act}"/*(N/); do
        session=$(basename "${sessiondir}")
        if ! session_alive "${session}"; then
            diag_log "orphan session detected: ${session}"
            local parts pane window
            for panedir in "${sessiondir}"/*/*(N/); do
                parts=("${(s:/:)panedir}")
                pane="${parts[-1]}"
                window="${parts[-2]}"
                archive_pane_dir "${session}" "${window}" "${pane}"
            done
            rmdir -p "${sessiondir}" 2>/dev/null || true
        fi
    done
}

# --- Main ---

main() {
    if [[ $# -gt 0 ]]; then
        DIAG_HOOK="shepherd.hook"
    else
        DIAG_HOOK="shepherd.cron"
    fi
    resolve_diag_log

    diag_log "invoked (pid=$$)"

    if [[ -z "${TDS_LOG_DIR:-}" ]]; then
        diag_log "TDS_LOG_DIR not set — aborting"
        warn_no_log_dir
        exit 1
    fi

    # Secure the log directory and its contents
    if [[ -d "${TDS_LOG_DIR}" ]]; then
        chmod -R u+rwX,go-rwx "${TDS_LOG_DIR}"
    fi

    if [[ $# -gt 0 ]]; then
        run_hook_mode "$1" "$2" "$3"
    else
        run_cron_mode
    fi
}

main "$@"
