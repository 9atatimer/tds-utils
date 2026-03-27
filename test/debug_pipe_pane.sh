#!/bin/zsh
# debug_pipe_pane.sh — diagnose why pipe-pane doesn't open from run-shell
set -euo pipefail

TEST_DIR=$(mktemp -d /tmp/lh-pipe-debug.XXXXXX)
SESSION="pipe-dbg"

cleanup() {
    tmux kill-session -t "${SESSION}" 2>/dev/null || true
    rm -rf "${TEST_DIR}" /tmp/pipe-direct.log /tmp/pipe-runshell.log
}
trap cleanup EXIT

mkdir -p "${TEST_DIR}/active" "${TEST_DIR}/archived"
tmux new-session -d -s "${SESSION}"

echo "=== Test 1: pipe-pane directly from CLI ==="
tmux pipe-pane -t "${SESSION}" -o "cat >> /tmp/pipe-direct.log"
echo "pipe status: $(tmux display-message -t ${SESSION} -p '#{pane_pipe}')"
tmux send-keys -t "${SESSION}" "echo direct-test" Enter
sleep 1
echo "file contents:"
cat /tmp/pipe-direct.log 2>&1 || echo "(no file)"
tmux pipe-pane -t "${SESSION}"  # close pipe

echo ""
echo "=== Test 2: pipe-pane from run-shell (no target) ==="
tmux run-shell -t "${SESSION}" "tmux pipe-pane -o 'cat >> /tmp/pipe-runshell.log'"
echo "pipe status: $(tmux display-message -t ${SESSION} -p '#{pane_pipe}')"
tmux send-keys -t "${SESSION}" "echo runshell-test" Enter
sleep 1
echo "file contents:"
cat /tmp/pipe-runshell.log 2>&1 || echo "(no file)"
tmux pipe-pane -t "${SESSION}"  # close pipe

echo ""
echo "=== Test 3: pipe-pane from run-shell (explicit target) ==="
tmux run-shell -t "${SESSION}" "tmux pipe-pane -t '${SESSION}' -o 'cat >> /tmp/pipe-runshell.log'"
echo "pipe status: $(tmux display-message -t ${SESSION} -p '#{pane_pipe}')"
tmux send-keys -t "${SESSION}" "echo target-test" Enter
sleep 1
echo "file contents:"
cat /tmp/pipe-runshell.log 2>&1 || echo "(no file)"
tmux pipe-pane -t "${SESSION}"  # close pipe

echo ""
echo "=== Test 4: logging script via run-shell with zsh -f ==="
tmux run-shell -t "${SESSION}" "PATH='${PATH}' TDS_LOG_DIR='${TEST_DIR}' /bin/zsh -f $(dirname $0)/../bin/tmux_logging.sh"
echo "pipe status: $(tmux display-message -t ${SESSION} -p '#{pane_pipe}')"
tmux send-keys -t "${SESSION}" "echo script-test" Enter
sleep 1
echo "diag log:"
cat "${TEST_DIR}/log-hoarder.logging.log" 2>&1 || echo "(no diag)"
echo "active files:"
find "${TEST_DIR}/active" -type f 2>/dev/null || echo "(none)"

echo ""
echo "=== Test 5: logging script via run-shell WITHOUT zsh -f ==="
# This uses .zshenv's TDS_LOG_DIR, so pipe to real log dir
tmux pipe-pane -t "${SESSION}"  # close any prior pipe
tmux run-shell -t "${SESSION}" "/bin/zsh $(dirname $0)/../bin/tmux_logging.sh"
echo "pipe status: $(tmux display-message -t ${SESSION} -p '#{pane_pipe}')"
tmux send-keys -t "${SESSION}" "echo nof-test" Enter
sleep 1
echo "real log dir active files:"
find ~/.local/share/log-hoarder/active/${SESSION} -type f 2>/dev/null || echo "(none)"

echo ""
echo "=== Done ==="
