#!/usr/bin/env bash
# tunnel.sh — SSH tunnel management for the local OpenAI-compatible endpoint.
#
# Forwards localhost:<local_port> -> remote vLLM <remote_port>. The remote binds
# vLLM to localhost only, so the tunnel is the sole access path.
# Prerequisites: ssh.
# Side effects: spawns/kills a background ssh process; writes the pid to state.

# --- Action functions --------------------------------------------------------

# Return 0 if the local endpoint answers an OpenAI-compatible health/models probe.
tunnel_endpoint_ready() {
    local local_port="$1"
    curl -fsS --max-time 3 "http://localhost:${local_port}/v1/models" >/dev/null 2>&1
}

# Kill a tunnel by pid if it is still alive.
tunnel_kill() {
    local pid="$1"
    [[ -n "${pid}" ]] || return 0
    if kill -0 "${pid}" 2>/dev/null; then
        kill "${pid}" 2>/dev/null || true
    fi
}

# --- Flow functions ----------------------------------------------------------

# Open a background SSH tunnel. Echoes the tunnel pid on success.
# Usage: tunnel_open <host> <ssh_port> <local_port> <remote_port> <key_file>
tunnel_open() {
    local host="$1" ssh_port="$2" local_port="$3" remote_port="$4" key_file="$5"
    ssh -f -N \
        -o StrictHostKeyChecking=accept-new \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=15 \
        -i "${key_file}" \
        -p "${ssh_port}" \
        -L "${local_port}:localhost:${remote_port}" \
        "root@${host}"
    # `ssh -f` backgrounds itself; find the listener pid for our local port.
    # `-n` selects the newest match, so a stale prior tunnel can't be recorded.
    # `|| true`: pgrep exits non-zero when there's no match, which would abort
    # the caller's `remvllm run` under set -e; an empty pid is handled there.
    pgrep -n -f "ssh.*-L ${local_port}:localhost:${remote_port}" || true
}
