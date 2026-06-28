#!/usr/bin/env bash
# watchdog.sh — client-side TTL enforcement (the "suspenders").
#
# The server-side watchdog (container/watchdog.sh) is the "belt": it self-
# destructs the node when no SSH session is present. This client watchdog tears
# the node down when the TTL expires AND the endpoint is idle, extending a grace
# window if a request is in flight.
# Prerequisites: bash, date.
# Side effects: invokes the orchestrator's teardown when TTL lapses.

# --- Action functions --------------------------------------------------------

# Echo epoch seconds for an ISO-8601 timestamp (GNU or BSD date).
watchdog_epoch() {
    local ts="$1"
    date -d "${ts}" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "${ts}" +%s 2>/dev/null
}

# Return 0 if `now` is at or past `expiry` (both ISO-8601).
watchdog_expired() {
    local expiry="$1" now="${2:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
    local e n
    e="$(watchdog_epoch "${expiry}")"
    n="$(watchdog_epoch "${now}")"
    [[ -n "${e}" && -n "${n}" ]] || return 1
    (( n >= e ))
}

# Echo an ISO-8601 timestamp `minutes` from now (UTC).
watchdog_ttl_from_now() {
    local minutes="$1"
    date -u -d "+${minutes} minutes" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
        || date -u -v "+${minutes}M" +%Y-%m-%dT%H:%M:%SZ
}
