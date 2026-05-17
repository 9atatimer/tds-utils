#!/usr/bin/env bash
# 06_pre_hook_failure_aborts.sh
# Given a pre-hook that exits non-zero, when clai runs, then the agent is NOT
# launched and clai exits with the hook's exit code.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    init_scenario "06_pre_abort"
    write_hook "${FAKE_HOME}" claude pre 10-fail \
        $'#!/usr/bin/env bash\nprintf "ran-pre\\n" >> "${SENTINEL}"\nexit 7\n'
    make_agent claude 0

    local rc=0
    run_clai proj claude >/dev/null 2>&1 || rc=$?
    if (( rc != 7 )); then
        echo "FAIL: expected exit 7, got ${rc}" >&2; return 1
    fi
    local got; got="$(cat "${SENTINEL}")"
    if ! grep -q '^ran-pre$' <<<"${got}"; then
        echo "FAIL: pre-hook should have run:" >&2; echo "${got}" >&2; return 1
    fi
    if grep -q '^agent:claude' <<<"${got}"; then
        echo "FAIL: agent should not have run:" >&2; echo "${got}" >&2; return 1
    fi
}

main "$@"
