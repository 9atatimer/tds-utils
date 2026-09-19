#!/bin/zsh
# tmux_shepherd.sh — log lifecycle manager for log-hoarder
#
# Invoked two ways:
#
#   1. tmux pane-exited hook -- args: SESSION_ID WINDOW_ID PANE_ID
#      - Moves that pane's log dir from active/ to archived/
#      - Sweeps active/ for orphaned pane dirs (sessions no longer alive)
#
#   2. cron (no args) — straggler sweep
#      - Sweeps archived/ for unprocessed pane dirs (no slug.txt present)
#      - Delegates to log_brander for LLM slug generation
#
# Directory convention (shared with tmux_logging.sh):
#   active/$SESSION/@WINDOW/%PANE/HHMMSS.log
#   active/$SESSION/name.txt                        (human-readable session name)
#   active/$SESSION/created.txt                     (session creation stamp)
#   archived/$SESSION/@WINDOW/%PANE/HHMMSS.log      (moved, not yet branded)
#   archived/$SESSION/name.txt
#   archived/$SESSION/@WINDOW/%PANE/slug.txt        (written by log_brander)
#
# The keys are tmux's IMMUTABLE ids ($N/@N/%N), never the session name -- a
# rename must not make a live session look dead to the sweep (issue #307).

set -euo pipefail
umask 077

# Resolved at load time: inside a zsh function $0 is the function's name,
# not the script's path. :A follows bin/ symlinks back to this directory.
SCRIPT_DIR="${0:A:h}"

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

# The brander that ships with THIS checkout, so a shepherd run out of a
# worktree brands with that worktree's code. LOG_BRANDER overrides.
brander_path() {
    echo "${LOG_BRANDER:-${SCRIPT_DIR}/log_brander}"
}

# Move a pane directory from active/ to archived/, preserving the
# session/window/pane hierarchy and the recorded session name.
archive_pane_dir() {
    local session="$1" window="$2" pane="$3"
    local src="$(active_dir)/${session}/${window}/${pane}"
    local dst="$(archived_dir)/${session}/${window}/${pane}"

    [[ -d "${src}" ]] || return 0

    mkdir -p "$(dirname "${dst}")"
    # Never mv onto an occupied destination: mv would move src INSIDE it,
    # nesting one session's logs under another's. Ids are reused across tmux
    # server restarts, so the destination really can be occupied.
    if [[ -e "${dst}" ]]; then
        local n=1
        while [[ -e "${dst}.${n}" ]]; do
            (( n++ ))
        done
        diag_log "destination occupied: ${dst} -- archiving as ${dst}.${n}"
        dst="${dst}.${n}"
    fi
    mv "${src}" "${dst}"
    archive_session_name "${session}"
    diag_log "archived: ${src} → ${dst}"
}

# Carry the human-readable name across with the logs, so the archived tree is
# still readable by someone who thinks in session names rather than in ids.
archive_session_name() {
    local session="$1"
    local src="$(active_dir)/${session}/name.txt"
    local dst="$(archived_dir)/${session}/name.txt"

    [[ -f "${src}" ]] || return 0
    mkdir -p "$(dirname "${dst}")"
    cp "${src}" "${dst}"
}

# Drop an emptied session dir from active/, taking its metadata with it -- but
# only once nothing else is left, so a pane dir that failed to move keeps its
# label.
retire_session_dir() {
    local session="$1"
    local sessiondir="$(active_dir)/${session}"
    local windowdir remaining leftover logs_remain=0

    for windowdir in "${sessiondir}"/*(N/); do
        rmdir "${windowdir}" 2>/dev/null || true
    done

    remaining=("${sessiondir}"/*(ND))
    for leftover in "${remaining[@]}"; do
        case "${leftover:t}" in
            name.txt|created.txt) ;;
            *) logs_remain=1 ;;
        esac
    done
    if (( logs_remain == 0 )); then
        rm -f "${sessiondir}/name.txt" "${sessiondir}/created.txt"
    fi
    rmdir "${sessiondir}" 2>/dev/null || true
}

# Returns true if any live session answers to this directory key.
#
# Keys are immutable session ids ($N) since issue #307; directories written
# before that are keyed on the mutable session NAME. Both lists are consulted
# rather than inferring which kind a key is from its shape -- tmux accepts
# "$1" as a session NAME, so the shape proves nothing. The bias is
# deliberate: holding a directory in active/ one sweep too long costs nothing,
# while archiving a live one out from under its open pipe is the whole defect.
session_alive() {
    local key="$1"
    tmux list-sessions -F $'#{session_id}\n#S' 2>/dev/null | grep -qxF -- "${key}"
}

# Re-record every live session's name: names change under `rename-session`,
# and the id-keyed directory is deliberately blind to that.
refresh_session_names() {
    local sid name
    tmux list-sessions -F $'#{session_id}\t#S' 2>/dev/null | while IFS=$'\t' read -r sid name; do
        [[ -d "$(active_dir)/${sid}" ]] || continue
        print -r -- "${name}" > "$(active_dir)/${sid}/name.txt"
    done
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
    local brander
    brander=$(brander_path)

    if [[ ! -f "${brander}" ]]; then
        diag_log "brander not found: ${brander} -- skipping"
        return 0
    fi
    diag_log "branding: ${panedir}"
    # Run through zsh, as tmux does for the hook scripts: the repo's scripts
    # are not marked executable.
    /bin/zsh "${brander}" "${panedir}" || true
}

# --- Flow functions ---

# Called from tmux hook: archive this pane's dir, then sweep for orphans.
# Trust but verify: tmux format variables may resolve to the wrong session
# during teardown, so confirm the session is actually dead before archiving.
run_hook_mode() {
    local session="$1" window="$2" pane="$3"

    diag_log "hook invoked: session=${session} window=${window} pane=${pane}"
    refresh_session_names
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

    refresh_session_names
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
    local act key parts window pane sessiondir panedir
    act=$(active_dir)

    for sessiondir in "${act}"/*(N/); do
        key="${sessiondir:t}"
        if ! session_alive "${key}"; then
            diag_log "orphan session detected: ${key}"
            for panedir in "${sessiondir}"/*/*(N/); do
                parts=("${(s:/:)panedir}")
                pane="${parts[-1]}"
                window="${parts[-2]}"
                archive_pane_dir "${key}" "${window}" "${pane}"
            done
            retire_session_dir "${key}"
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
