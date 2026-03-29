#!/bin/zsh
# debug_tmux_mouse.sh — dump tmux mouse-related config and bindings
set -euo pipefail

echo "=== tmux version ==="
tmux -V

echo ""
echo "=== mouse setting ==="
tmux show -g mouse

echo ""
echo "=== default-terminal ==="
tmux show -g default-terminal

echo ""
echo "=== terminal-features ==="
tmux show -g terminal-features 2>/dev/null || echo "(not set)"

echo ""
echo "=== TERM inside tmux ==="
echo "TERM=$TERM"

echo ""
echo "=== copy-mode key table (mouse bindings) ==="
tmux list-keys -T copy-mode | grep -i mouse

echo ""
echo "=== copy-mode-vi key table (mouse bindings) ==="
tmux list-keys -T copy-mode-vi | grep -i mouse 2>/dev/null || echo "(none)"

echo ""
echo "=== root key table (mouse bindings) ==="
tmux list-keys -T root | grep -i mouse

echo ""
echo "=== mode-keys setting ==="
tmux show -g mode-keys

echo ""
echo "=== all copy-mode bindings ==="
tmux list-keys -T copy-mode
