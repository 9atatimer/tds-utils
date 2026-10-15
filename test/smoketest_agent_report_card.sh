#!/usr/bin/env bash
# smoketest_agent_report_card.sh -- bin/agent-report-card counts and deltas.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CARD="$(dirname "${SCRIPT_DIR}")/bin/agent-report-card"
REPO=""

# --- Action functions ---

fail() { echo "FAIL: $1"; exit 1; }

cleanup() { [[ -n "$REPO" ]] && rm -rf "$REPO"; return 0; }

make_repo() {
    REPO=$(mktemp -d)
    git -C "$REPO" init -q
    git -C "$REPO" config user.email t@t
    git -C "$REPO" config user.name t
    printf 'Never do x.\nplain line\n' >"$REPO/A.md"
    git -C "$REPO" add A.md
    git -C "$REPO" commit -qm base
    printf 'Never do x.\n' >"$REPO/A.md"
}

# --- Flow functions ---

run_test() {
    local out
    make_repo
    out=$(cd "$REPO" && "$CARD" -f A.md -r HEAD)
    grep -q '| words | 5 | 3 | -2 (-40.0%) |' <<<"$out" || fail "word delta: $out"
    grep -q '| rule-lines | 1 | 1 | +0 (+0.0%) |' <<<"$out" || fail "rule delta: $out"
    echo "PASS"
}

trap cleanup EXIT INT TERM HUP
run_test
