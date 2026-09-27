#!/bin/zsh
# A-verify.zsh -- harness for spike A: fixture tmux server + clones, assert, time
#
# Never touches the default tmux server: everything is on socket "pr2s-spike".

set -euo pipefail

here="${0:A:h}"
sock="pr2s-spike"
work=""

# --- Action functions ---
mk_clone() {
    # mk_clone <dir> <branch> <origin-url>
    git init -q -b "$2" "$1"
    git -C "$1" -c user.name=spike -c user.email=spike@example.invalid \
        commit -q --allow-empty -m init
    git -C "$1" remote add origin "$3"
}

mk_worktree() {
    # mk_worktree <clone> <dir> <branch>
    git -C "$1" worktree add -q -b "$3" "$2"
}

new_session() {
    tmux -L "$sock" new-session -d -s "$1" -c "$2"
}

session_id_of() {
    tmux -L "$sock" display-message -p -t "$1" '#{session_id}'
}

cleanup() {
    tmux -L "$sock" kill-server 2>/dev/null || true
    [[ -n "$work" ]] && rm -rf "$work"
}

# --- Flow functions ---
build_fixture() {
    work=$(mktemp -d)
    mk_clone "$work/tds-utils" feature/x git@github.com:9atatimer/tds-utils.git
    mk_worktree "$work/tds-utils" "$work/tds-utils-wt" claude/foo
    mk_clone "$work/template-tools" main https://github.com/nine-at-a-time-media/template-tools.git
    mkdir -p "$work/nogit"

    tmux -L "$sock" kill-server 2>/dev/null || true
    new_session s1 "$work/tds-utils"
    tmux -L "$sock" split-window -t s1 -c "$work/tds-utils"   # 2 panes, 1 session
    new_session s2 "$work/tds-utils-wt"
    new_session s3 "$work/template-tools"
    new_session s4 "$work/nogit"
}

assert_lookup() {
    local want got
    want=$(session_id_of s2)
    got=$(zsh "$here/A-map.zsh" -L "$sock" -r 9atatimer/tds-utils -b claude/foo | cut -f1)
    if [[ "$got" != "$want" ]]; then
        print -u2 -- "FAIL: wanted $want got '$got'"
        exit 1
    fi
    print -- "PASS: 9atatimer/tds-utils claude/foo -> $got (s2)"
}

scale_up() {
    local i
    for i in {5..30}; do
        new_session "s$i" "$work/template-tools"
    done
}

run_verify() {
    trap cleanup EXIT
    build_fixture
    print -- "--- full map, 4 sessions (s1 has two panes, s4 has no git)"
    zsh "$here/A-map.zsh" -L "$sock" -t
    assert_lookup
    scale_up
    print -- "--- filtered lookup, 30 sessions"
    zsh "$here/A-map.zsh" -L "$sock" -t -r 9atatimer/tds-utils -b claude/foo
}

# --- Main ---
main() {
    run_verify
}

main "$@"
