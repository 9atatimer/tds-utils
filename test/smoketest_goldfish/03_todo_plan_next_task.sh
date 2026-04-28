#!/usr/bin/env bash
# 03_todo_plan_next_task.sh — first unchecked TODO_PLAN line surfaces in NEXT.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    todo=$'# Plan\n- [x] done\n- [ ] write the next big thing\n- [ ] another'
    make_fake_clone "todd/planner" "${todo}" >/dev/null
    out="$(run_goldfish 2>/dev/null)"
    if ! grep -q "write the next big thing" <<<"${out}"; then
        echo "FAIL: next-task line not surfaced. Output was:"
        echo "${out}"
        return 1
    fi
}

main "$@"
