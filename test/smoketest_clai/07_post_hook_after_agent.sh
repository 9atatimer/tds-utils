#!/usr/bin/env bash
# 07_post_hook_after_agent.sh
# Given a post-hook, when the agent exits, then the post-hook runs with
# CLAI_EXIT set to the agent's exit code; clai propagates the agent's exit
# code (not the hook's).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    init_scenario "07_post"
    write_hook "${FAKE_HOME}" claude post 10-mark \
        $'#!/usr/bin/env bash\nprintf "post:%s\\n" "${CLAI_EXIT}" >> "${SENTINEL}"\n'
    make_agent claude 3

    local rc=0
    run_clai proj claude >/dev/null 2>&1 || rc=$?
    if (( rc != 3 )); then
        echo "FAIL: expected agent exit 3 propagated, got ${rc}" >&2; return 1
    fi
    local got; got="$(cat "${SENTINEL}")"
    if ! grep -q '^post:3$' <<<"${got}"; then
        echo "FAIL: post-hook missing or CLAI_EXIT wrong:" >&2; echo "${got}" >&2; return 1
    fi
    # Ordering: agent line precedes post line.
    local agent_line post_line
    agent_line="$(grep -n '^agent:' <<<"${got}" | head -1 | cut -d: -f1)"
    post_line="$(grep -n '^post:' <<<"${got}" | head -1 | cut -d: -f1)"
    if (( agent_line >= post_line )); then
        echo "FAIL: post-hook should run after agent" >&2; return 1
    fi
}

main "$@"
