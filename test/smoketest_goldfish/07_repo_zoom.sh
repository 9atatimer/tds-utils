#!/usr/bin/env bash
# 07_repo_zoom.sh — `goldfish <repo>` renders a one-repo summary with every open task.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    local todo
    todo=$'# TODO_PLAN\n- [ ] task one\n- [x] done thing\n- [ ] task two\n- [ ] task three\n'
    make_fake_clone "todd/zoom-target" "${todo}" >/dev/null
    make_fake_clone "todd/other-repo" >/dev/null

    # Basename resolution should pick zoom-target out of two clones.
    out="$(run_goldfish zoom-target 2>/dev/null)"

    if ! grep -q "todd/zoom-target" <<<"${out}"; then
        echo "FAIL: repo name header missing:"
        echo "${out}"
        return 1
    fi
    for t in "task one" "task two" "task three"; do
        if ! grep -qF "${t}" <<<"${out}"; then
            echo "FAIL: open task '${t}' missing from zoom output:"
            echo "${out}"
            return 1
        fi
    done
    if grep -qF "done thing" <<<"${out}"; then
        echo "FAIL: completed task leaked into open-task list:"
        echo "${out}"
        return 1
    fi
    if ! grep -qi "recent commits" <<<"${out}"; then
        echo "FAIL: 'Recent commits' section missing:"
        echo "${out}"
        return 1
    fi
}

main "$@"
