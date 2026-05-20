#!/usr/bin/env bash
# 10_list_agents.sh
# Given clai.d/<agent>/ directories planted across $HOME and a nested level,
# when clai --list-agents runs, then every configured agent is listed once,
# sorted, even when an agent appears at more than one level.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

noop_hook=$'#!/usr/bin/env bash\n:\n'

main() {
    init_scenario "10_list_agents"

    # Global agents at $HOME.
    write_hook "${FAKE_HOME}" claude pre 10-mark "${noop_hook}"
    write_hook "${FAKE_HOME}" gemini pre 10-mark "${noop_hook}"
    # Project level: re-declare claude (so it spans two levels) and add codex.
    write_hook "${FAKE_HOME}/proj" claude post 10-mark "${noop_hook}"
    write_hook "${FAKE_HOME}/proj" codex pre 10-mark "${noop_hook}"

    local out rc=0
    out="$(run_clai proj --list-agents)" || rc=$?
    if (( rc != 0 )); then
        echo "FAIL: clai --list-agents exited ${rc}" >&2; return 1
    fi

    local expected
    expected=$'claude\ncodex\ngemini'
    if [[ "${out}" != "${expected}" ]]; then
        echo "FAIL: agent list mismatch" >&2
        echo "expected:" >&2; echo "${expected}" >&2
        echo "got:" >&2; echo "${out}" >&2
        return 1
    fi

    # -l is the documented short form and must behave identically.
    local short rc2=0
    short="$(run_clai proj -l)" || rc2=$?
    if (( rc2 != 0 )) || [[ "${short}" != "${expected}" ]]; then
        echo "FAIL: clai -l disagrees with --list-agents:" >&2
        echo "${short}" >&2; return 1
    fi
}

main "$@"
