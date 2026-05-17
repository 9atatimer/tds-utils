#!/usr/bin/env bash
# 05_stop_at_home.sh
# Given a clai.d/ above $HOME (an "ancestor we should ignore"), when clai runs,
# then that ancestor's hooks are NOT picked up.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    init_scenario "05_stop_at_home"
    # Plant a hook in the directory ABOVE the fake HOME — must not run.
    write_hook "$(dirname "${FAKE_HOME}")" claude pre 10-mark \
        $'#!/usr/bin/env bash\nprintf "above-home\\n" >> "${SENTINEL}"\n'
    # Plant a hook at HOME — must run.
    write_hook "${FAKE_HOME}" claude pre 20-home \
        $'#!/usr/bin/env bash\nprintf "home\\n" >> "${SENTINEL}"\n'
    make_agent claude 0
    run_clai proj claude >/dev/null

    local got; got="$(cat "${SENTINEL}")"
    if grep -q '^above-home$' <<<"${got}"; then
        echo "FAIL: walked above HOME:" >&2; echo "${got}" >&2; return 1
    fi
    if ! grep -q '^home$' <<<"${got}"; then
        echo "FAIL: HOME-level hook did not run:" >&2; echo "${got}" >&2; return 1
    fi
}

main "$@"
