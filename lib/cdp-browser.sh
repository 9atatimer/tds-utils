#!/usr/bin/env bash
# cdp-browser.sh -- shared mechanics for a CDP-tethered browser whose profile
# lives in the current repo's .cdp/ sandbox.
#
# Sourced by bin/cdp and bin/realchrome-cdp. Browser-agnostic: callers pass
# the sandbox name (the directory under .cdp/) and the executable; nothing
# here knows which browsers exist.
#
# Sandbox layout, per browser:
#   <repo>/.cdp/<name>/profile       --user-data-dir (live logins; gitignored)
#   <repo>/.cdp/<name>/browser.pid   pid of the process we launched
#   <repo>/.cdp/<name>/port          the debugging port it was launched on
#   <repo>/.cdp/<name>/browser.log   the browser's stdout/stderr
#
# Seams (for hermetic tests; see test/smoketest_cdp.sh):
#   CDP_PROBE         "$CDP_PROBE" PORT        -- exit 0 iff CDP answers
#   CDP_LISTENER_PID  "$CDP_LISTENER_PID" PORT -- print pid listening on PORT
#
# Bash 3.2 compatible (macOS /bin/bash).

CDP_DEFAULT_PORT=9322
CDP_READY_TRIES=80        # x 0.25s = 20s for a cold start
CDP_STOP_TRIES=40         # x 0.25s = 10s for a clean shutdown

# --- Action functions ---

cdp_die() { echo "${CDP_PROG:-cdp}: $*" >&2; exit 1; }
cdp_note() { echo "${CDP_PROG:-cdp}: $*"; }

# cdp_repo_root -- print the enclosing git repo's top level, or die.
cdp_repo_root() {
    git rev-parse --show-toplevel 2>/dev/null \
        || cdp_die "not inside a git repo; the browser profile lives in <repo>/.cdp/"
}

# cdp_require_ignored <root> -- die unless <root>/.cdp/ is gitignored.
cdp_require_ignored() {
    local root="$1"
    git -C "${root}" check-ignore -q "${root}/.cdp/profile-probe" \
        || cdp_die "${root}/.cdp/ is not gitignored; the profile holds live session cookies. Add '.cdp/' to ${root}/.gitignore first."
}

# cdp_probe <port> -- exit 0 iff a CDP endpoint answers on <port>.
cdp_probe() {
    local port="$1"
    if [ -n "${CDP_PROBE:-}" ]; then
        "${CDP_PROBE}" "${port}"
        return
    fi
    curl -s -o /dev/null --max-time 1 "http://127.0.0.1:${port}/json/version"
}

# cdp_listener_pid <port> -- print the pid listening on <port>, if any.
cdp_listener_pid() {
    local port="$1"
    if [ -n "${CDP_LISTENER_PID:-}" ]; then
        "${CDP_LISTENER_PID}" "${port}"
        return
    fi
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null | head -1 || true
}

# cdp_recorded_pid <dir> -- print the recorded pid if that process is alive.
cdp_recorded_pid() {
    local dir="$1" pid
    [ -f "${dir}/browser.pid" ] || return 0
    pid="$(cat "${dir}/browser.pid")"
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
        printf '%s' "${pid}"
    fi
}

# cdp_spawn <exe> <profile> <port> <log> [extra-arg...] -- start the browser
# detached with any browser-specific extra args; print its pid.
cdp_spawn() {
    local exe="$1" profile="$2" port="$3" log="$4"
    shift 4
    nohup "${exe}" \
        --remote-debugging-port="${port}" \
        --user-data-dir="${profile}" \
        --no-first-run \
        --no-default-browser-check \
        "$@" \
        > "${log}" 2>&1 < /dev/null &
    printf '%s' "$!"
}

# cdp_wait_ready <port> <pid> -- wait for CDP on <port>; fail if <pid> dies.
cdp_wait_ready() {
    local port="$1" pid="$2" i=0
    while [ "${i}" -lt "${CDP_READY_TRIES}" ]; do
        cdp_probe "${port}" && return 0
        kill -0 "${pid}" 2>/dev/null || return 1
        i=$((i + 1))
        sleep 0.25
    done
    return 1
}

# cdp_wait_exit <pid> -- wait for <pid> to exit; return 1 on timeout.
cdp_wait_exit() {
    local pid="$1" i=0
    while [ "${i}" -lt "${CDP_STOP_TRIES}" ]; do
        kill -0 "${pid}" 2>/dev/null || return 0
        i=$((i + 1))
        sleep 0.25
    done
    return 1
}

# --- Flow functions ---

# cdp_up <root> <name> <exe> <port> [extra-arg...]
cdp_up() {
    local root="$1" name="$2" exe="$3" port="$4"
    shift 4
    local dir="${root}/.cdp/${name}" mine holder pid

    [ -x "${exe}" ] || cdp_die "${name}: no executable at ${exe}"
    cdp_require_ignored "${root}"

    mine="$(cdp_recorded_pid "${dir}")"
    if cdp_probe "${port}"; then
        holder="$(cdp_listener_pid "${port}")"
        if [ -n "${mine}" ] && [ "${holder}" = "${mine}" ]; then
            cdp_note "${name} already up on port ${port} (pid ${mine})"
            return 0
        fi
        cdp_die "port ${port} is held by pid ${holder:-unknown}, not this repo's ${name} profile. Bring that browser down, or pass --port."
    fi
    [ -z "${mine}" ] || cdp_die "${name} (pid ${mine}) is running but not answering on port ${port}; run '${CDP_PROG} down' first."

    mkdir -p "${dir}/profile"
    pid="$(cdp_spawn "${exe}" "${dir}/profile" "${port}" "${dir}/browser.log" "$@")"
    printf '%s' "${pid}" > "${dir}/browser.pid"
    printf '%s' "${port}" > "${dir}/port"

    cdp_wait_ready "${port}" "${pid}" \
        || cdp_die "${name} did not answer on port ${port}; see ${dir}/browser.log"
    cdp_note "${name} up on http://127.0.0.1:${port} (pid ${pid}, profile ${dir}/profile)"
}

# cdp_down <root> <name>
cdp_down() {
    local root="$1" name="$2"
    local dir="${root}/.cdp/${name}" pid

    pid="$(cdp_recorded_pid "${dir}")"
    if [ -z "${pid}" ]; then
        rm -f "${dir}/browser.pid"
        cdp_note "${name} not running"
        return 0
    fi
    kill -TERM "${pid}" 2>/dev/null || true
    if ! cdp_wait_exit "${pid}"; then
        cdp_note "${name} (pid ${pid}) ignored SIGTERM; sending SIGKILL"
        kill -KILL "${pid}" 2>/dev/null || true
    fi
    rm -f "${dir}/browser.pid"
    cdp_note "${name} down"
}

# cdp_status <root> <name>
cdp_status() {
    local root="$1" name="$2"
    local dir="${root}/.cdp/${name}" pid port

    pid="$(cdp_recorded_pid "${dir}")"
    port="$(cat "${dir}/port" 2>/dev/null || printf '%s' "${CDP_DEFAULT_PORT}")"
    if [ -n "${pid}" ] && cdp_probe "${port}"; then
        cdp_note "${name} up on http://127.0.0.1:${port} (pid ${pid}, profile ${dir}/profile)"
    elif [ -n "${pid}" ]; then
        cdp_note "${name} running (pid ${pid}) but not answering on port ${port}"
    else
        cdp_note "${name} not running (profile ${dir}/profile)"
    fi
}
