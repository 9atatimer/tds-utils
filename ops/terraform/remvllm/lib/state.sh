#!/usr/bin/env bash
# state.sh — per-hostname runtime state for remvllm.
#
# State lives at <state_dir>/<hostname>/state.json so two machines can manage
# their own remote nodes independently. The whole state/ tree is gitignored.
# Prerequisites: jq.
# Side effects: reads/writes files under the state dir.

# --- Action functions --------------------------------------------------------

# Echo the state directory for this host, creating it if needed.
state_host_dir() {
    local base="$1"
    local host="${REMVLLM_FAKE_HOSTNAME:-$(hostname -s 2>/dev/null || hostname)}"
    local dir="${base}/${host}"
    mkdir -p "${dir}"
    printf '%s\n' "${dir}"
}

# Echo the path to this host's state.json.
state_file() {
    local base="$1"
    printf '%s/state.json\n' "$(state_host_dir "${base}")"
}

# --- Flow functions ----------------------------------------------------------

# Write a state.json from key=value pairs. Numbers and booleans are passed
# through as JSON; everything else is a string. Usage:
#   state_write <base> instance_id=spheron-abc gpu_count=8 spot=true ...
state_write() {
    local base="$1"; shift
    local file
    file="$(state_file "${base}")"
    local jq_args=() filter="{}" pair key val
    for pair in "$@"; do
        key="${pair%%=*}"
        val="${pair#*=}"
        if [[ "${val}" =~ ^-?[0-9]+(\.[0-9]+)?$ || "${val}" == "true" || "${val}" == "false" || "${val}" == "null" ]]; then
            filter="${filter} | .${key} = ${val}"
        else
            jq_args+=(--arg "${key}" "${val}")
            filter="${filter} | .${key} = \$${key}"
        fi
    done
    jq -n "${jq_args[@]}" "${filter}" > "${file}"
}

# Echo a single field from state.json, or empty if absent.
state_read() {
    local base="$1" field="$2"
    local file
    file="$(state_file "${base}")"
    [[ -f "${file}" ]] || return 0
    jq -r --arg f "${field}" '.[$f] // empty' "${file}"
}

# Return 0 if a state.json exists with a non-empty instance_id.
state_has_instance() {
    local base="$1"
    [[ -n "$(state_read "${base}" instance_id)" ]]
}

# Remove this host's state.json.
state_clear() {
    local base="$1"
    rm -f "$(state_file "${base}")"
}
