#!/bin/zsh
# A-map.zsh -- spike A: (owner/repo, branch) -> tmux session from live tmux + git
#
# Emits one line per (session, repo, branch):
#   session_id<TAB>session_name<TAB>owner/repo<TAB>branch
# The tmux and git commands are the ones TMUX-HERD.DESIGN.md names, so the
# spike measures what the herd would measure. No daemon, no state.

set -euo pipefail
zmodload zsh/datetime

# --- Action functions ---
list_panes() {
    local -a cmd
    cmd=(tmux)
    [[ -n "$socket" ]] && cmd+=(-L "$socket")
    # tmux 3.4 rewrites a literal tab in -F output to "_" and emits a "\t"
    # escape as the two characters, so the separator is "|"; the path is
    # last so a "|" inside it survives the split.
    "${cmd[@]}" list-panes -a -F '#{session_id}|#{session_name}|#{pane_pid}|#{pane_current_path}'
}

git_common_dir() {
    git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null
}

git_branch() {
    git -C "$1" rev-parse --abbrev-ref HEAD 2>/dev/null || echo detached
}

git_origin() {
    git -C "$1" remote get-url origin 2>/dev/null || true
}

repo_path() {
    # owner/name from an ssh or https origin; else the clone dir under ~/workplace
    local origin="$1" common="$2" p=""
    case "$origin" in
        git@*:*)                 p="${origin#*:}" ;;
        ssh://*|https://*|http://*) p="${origin#*://}"; p="${p#*/}" ;;
    esac
    p="${p%.git}"
    if [[ -z "$p" ]]; then
        p="${common:h}"
        p="${p#$HOME/workplace/}"
        p="${p#$HOME/}"
    fi
    print -r -- "$p"
}

# --- Flow functions ---
map_sessions() {
    local sid name pid cwd common branch origin repo
    list_panes | while IFS='|' read -r sid name pid cwd; do
        common=$(git_common_dir "$cwd") || continue
        [[ -z "$common" ]] && continue
        branch=$(git_branch "$cwd")
        origin=$(git_origin "$cwd")
        repo=$(repo_path "$origin" "$common")
        print -r -- "${sid}	${name}	${repo}	${branch}"
    done | sort -u
}

filter_map() {
    local repo="$1" branch="$2" line sid name r b
    while IFS=$'\t' read -r sid name r b; do
        [[ -n "$repo" && "$r" != "$repo" ]] && continue
        [[ -n "$branch" && "$b" != "$branch" ]] && continue
        print -r -- "${sid}	${name}	${r}	${b}"
    done
}

run_map() {
    local repo="$1" branch="$2" timed="$3" t0 t1
    t0=$EPOCHREALTIME
    map_sessions | filter_map "$repo" "$branch"
    t1=$EPOCHREALTIME
    if [[ "$timed" == true ]]; then
        printf 'elapsed_ms=%d\n' $(( (t1 - t0) * 1000 )) >&2
    fi
}

usage() {
    print -u2 -- "usage: A-map.zsh [-L tmux-socket] [-r owner/repo] [-b branch] [-t]"
}

# --- Main ---
main() {
    local repo="" branch="" timed=false opt
    socket=""
    while getopts "L:r:b:th" opt; do
        case "$opt" in
            L) socket="$OPTARG" ;;
            r) repo="$OPTARG" ;;
            b) branch="$OPTARG" ;;
            t) timed=true ;;
            h) usage; exit 0 ;;
            *) usage; exit 64 ;;
        esac
    done
    run_map "$repo" "$branch" "$timed"
}

typeset -g socket
main "$@"
