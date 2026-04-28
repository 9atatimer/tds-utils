#!/usr/bin/env bash
# config.sh — shared environment + helpers for goldfish smoke tests
#
# Defines `init_smoke_env` (called once by run_all.sh after SMOKE_TMP is
# allocated) plus `run_goldfish` and `make_fake_clone` (called by every
# scenario). Sourcing this file is side-effect-free; init_smoke_env is the
# single mutator and writes ${SMOKE_CONFIG} based on ${SMOKE_TMP}.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GOLDFISH="${REPO_DIR}/goldfish/goldfish"

# --- Init --------------------------------------------------------------------

init_smoke_env() {
    if [[ -z "${SMOKE_TMP:-}" ]]; then
        echo "error: SMOKE_TMP must be set before init_smoke_env" >&2
        return 1
    fi
    export SMOKE_CLONES="${SMOKE_TMP}/clones"
    export SMOKE_CACHE="${SMOKE_TMP}/cache"
    export SMOKE_CONFIG="${SMOKE_TMP}/config.json"

    cat > "${SMOKE_CONFIG}" <<EOF
{
    "orgs": [],
    "agents": ["claude", "gemini", "opencode", "codex"],
    "roots": ["${SMOKE_CLONES}"]
}
EOF
}

# --- Action helpers ----------------------------------------------------------

# Run goldfish with the smoke config swapped in. Each scenario calls
# `run_goldfish [args...]` to invoke against the isolated environment.
run_goldfish() {
    if [[ ! -d "${SMOKE_TMP}/goldfish" ]]; then
        cp -r "${REPO_DIR}/goldfish" "${SMOKE_TMP}/goldfish"
        cp "${SMOKE_CONFIG}" "${SMOKE_TMP}/goldfish/config.json"
    fi
    XDG_CACHE_HOME="${SMOKE_CACHE}" \
        python3 "${SMOKE_TMP}/goldfish/goldfish" "$@"
}

# Initialize a fake clone with a github remote inside SMOKE_CLONES.
# Usage: make_fake_clone <owner/repo> [todo_plan_content]
make_fake_clone() {
    local nameowner="$1"
    local todo="${2:-}"
    local dir="${SMOKE_CLONES}/$(basename "${nameowner}")"
    mkdir -p "${dir}"
    (
        cd "${dir}"
        git init -q
        git config user.email "test@example.com"
        git config user.name "test"
        git config commit.gpgsign false
        git remote add origin "git@github.com:${nameowner}.git"
        echo "x" > a.txt
        git add a.txt
        git commit -qm "first"
        if [[ -n "${todo}" ]]; then
            printf '%s\n' "${todo}" > TODO_PLAN.md
        fi
    )
    # Invalidate the clones cache so the new repo is picked up on the next run.
    rm -f "${SMOKE_CACHE}/goldfish/clones.json"
    echo "${dir}"
}

export -f run_goldfish make_fake_clone init_smoke_env
