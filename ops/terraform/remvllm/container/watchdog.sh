#!/usr/bin/env bash
# watchdog.sh — server-side idle monitor (the "belt").
#
# If no SSH session is present for WATCHDOG_TIMEOUT seconds, the node has been
# abandoned (e.g. the laptop slept and the client watchdog died). Self-destruct
# to stop the spend. Spot reclaim is the other backstop.
set -euo pipefail

WATCHDOG_TIMEOUT="${WATCHDOG_TIMEOUT:-600}"
POLL_INTERVAL=30

active_ssh_sessions() {
    # Count established inbound SSH connections (excludes the listener). Always
    # emit an integer. `ss` ships via iproute2 in the appliance image; if it is
    # somehow missing we report 0 rather than an empty string (which would make
    # the numeric comparison in main() fail under set -e).
    if ! command -v ss >/dev/null 2>&1; then
        echo 0
        return 0
    fi
    ss -tn state established '( sport = :22 )' 2>/dev/null | grep -c ':22 ' || true
}

main() {
    local idle=0
    while true; do
        if [[ "$(active_ssh_sessions)" -gt 0 ]]; then
            idle=0
        else
            idle=$((idle + POLL_INTERVAL))
        fi
        if (( idle >= WATCHDOG_TIMEOUT )); then
            echo "watchdog: idle ${idle}s >= ${WATCHDOG_TIMEOUT}s — self-destructing"
            shutdown -h now || poweroff -f || halt -f
            exit 0
        fi
        sleep "${POLL_INTERVAL}"
    done
}

main "$@"
