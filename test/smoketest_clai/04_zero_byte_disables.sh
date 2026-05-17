#!/usr/bin/env bash
# 04_zero_byte_disables.sh
# Given a global hook and a zero-byte file with the same basename at project
# level, when clai runs, then the global hook is shadowed and does NOT run.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    init_scenario "04_zero_byte"
    write_hook "${FAKE_HOME}" claude pre 10-mark \
        $'#!/usr/bin/env bash\nprintf "global\\n" >> "${SENTINEL}"\n'
    local proj="${FAKE_HOME}/proj"
    # Zero-byte shadow.
    write_hook "${proj}" claude pre 10-mark ""
    make_agent claude 0
    run_clai proj claude >/dev/null

    local got; got="$(cat "${SENTINEL}")"
    if grep -q '^global$' <<<"${got}"; then
        echo "FAIL: zero-byte should have nulled out the global hook:" >&2
        echo "${got}" >&2; return 1
    fi
    if ! grep -q '^agent:claude' <<<"${got}"; then
        echo "FAIL: agent did not run:" >&2; echo "${got}" >&2; return 1
    fi
}

main "$@"
