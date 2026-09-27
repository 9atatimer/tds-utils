#!/bin/zsh
# B-jump.zsh -- spike B: bring Terminal.app forward on a tmux session (macOS only)
#
# NOT RUN: authored in a Linux container. Expected behaviour on the Mac:
#   - a client is attached somewhere  -> that client switches to the target
#     session and Terminal comes forward on it
#   - no client attached              -> a new Terminal window opens attached
#     to the target session
# Target is a session id ($N) or name.

set -euo pipefail

# --- Action functions ---
attached_client() {
    tmux list-clients -F '#{client_name}' 2>/dev/null | head -n 1
}

switch_client() {
    tmux switch-client -c "$1" -t "$2"
}

open_new_window() {
    osascript -e "tell application \"Terminal\" to do script \"tmux attach -t '$1'\""
}

activate_terminal() {
    osascript -e 'tell application "Terminal" to activate'
}

# --- Flow functions ---
jump_to() {
    local target="$1" client
    client=$(attached_client)
    if [[ -n "$client" ]]; then
        switch_client "$client" "$target"
    else
        open_new_window "$target"
    fi
    activate_terminal
}

# --- Main ---
main() {
    [[ $# -eq 1 ]] || { print -u2 -- "usage: B-jump.zsh <session_id|session_name>"; exit 64; }
    jump_to "$1"
}

main "$@"
