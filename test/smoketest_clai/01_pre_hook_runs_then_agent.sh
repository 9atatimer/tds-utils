#!/usr/bin/env bash
# 01_pre_hook_runs_then_agent.sh
# Given a single global pre-hook for `claude`, when clai runs, then the hook
# fires before the agent and both leave traces in expected order.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    init_scenario "01_pre_then_agent"
    write_hook "${FAKE_HOME}" claude pre 10-mark \
        $'#!/usr/bin/env bash\nprintf "pre:%s cwd:%s\\n" "${CLAI_AGENT}" "${CLAI_CWD}" >> "${SENTINEL}"\n'
    make_agent claude 0
    run_clai workdir claude --some-flag >/dev/null

    local got
    got="$(cat "${SENTINEL}")"
    if ! grep -q '^pre:claude' <<<"${got}"; then
        echo "FAIL: pre-hook trace missing:" >&2; echo "${got}" >&2; return 1
    fi
    if ! grep -q '^agent:claude args:--some-flag' <<<"${got}"; then
        echo "FAIL: agent trace missing:" >&2; echo "${got}" >&2; return 1
    fi
    # Order: pre must precede agent.
    local pre_line agent_line
    pre_line="$(grep -n '^pre:' <<<"${got}" | head -1 | cut -d: -f1)"
    agent_line="$(grep -n '^agent:' <<<"${got}" | head -1 | cut -d: -f1)"
    if (( pre_line >= agent_line )); then
        echo "FAIL: agent ran before pre-hook" >&2; return 1
    fi
}

main "$@"
