#!/usr/bin/env bash
# config.sh — shared environment for goldfish smoke tests
#
# Sourced by run_all.sh (which sets up SMOKE_TMP and SMOKE_CONFIG) and by
# every scenario script. SMOKE_TMP is an isolated tmp tree; SMOKE_CONFIG is
# a goldfish config.json pointing at $SMOKE_TMP/clones as the only root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GOLDFISH="${REPO_DIR}/goldfish/goldfish"

if [[ -z "${SMOKE_TMP:-}" ]]; then
    echo "error: SMOKE_TMP must be set by run_all.sh before sourcing config.sh" >&2
    exit 1
fi

export SMOKE_CLONES="${SMOKE_TMP}/clones"
export SMOKE_CACHE="${SMOKE_TMP}/cache"
export SMOKE_CONFIG="${SMOKE_TMP}/config.json"

# Build a goldfish config pointing only at our tmp clones dir.
cat > "${SMOKE_CONFIG}" <<EOF
{
    "orgs": [],
    "agents": ["claude", "gemini", "opencode", "codex"],
    "roots": ["${SMOKE_CLONES}"]
}
EOF

# Run goldfish with the smoke config swapped in. Each scenario calls
# `run_goldfish [args...]` to invoke against the isolated environment.
run_goldfish() {
    # goldfish reads config from goldfish/config.json next to the script;
    # to override hermetically without touching the real file, copy
    # goldfish/ into SMOKE_TMP, drop our config in, and run from there.
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
        git commit -qm "first" 2>/dev/null || true
        if [[ -n "${todo}" ]]; then
            printf '%s\n' "${todo}" > TODO_PLAN.md
        fi
    )
    # Invalidate the clones cache so the new repo is picked up on the next run.
    rm -f "${SMOKE_CACHE}/goldfish/clones.json"
    echo "${dir}"
}

export -f run_goldfish make_fake_clone
