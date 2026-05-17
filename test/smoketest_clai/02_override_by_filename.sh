#!/usr/bin/env bash
# 02_override_by_filename.sh
# Given a global hook and a project-level hook with the same basename, when
# clai runs from the project, then only the project-level body executes.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    init_scenario "02_override"
    write_hook "${FAKE_HOME}" claude pre 10-mark \
        $'#!/usr/bin/env bash\nprintf "global\\n" >> "${SENTINEL}"\n'
    local proj="${FAKE_HOME}/proj"
    write_hook "${proj}" claude pre 10-mark \
        $'#!/usr/bin/env bash\nprintf "project\\n" >> "${SENTINEL}"\n'
    make_agent claude 0
    run_clai proj claude >/dev/null

    local got; got="$(cat "${SENTINEL}")"
    if grep -q '^global$' <<<"${got}"; then
        echo "FAIL: global hook should have been shadowed:" >&2; echo "${got}" >&2; return 1
    fi
    if ! grep -q '^project$' <<<"${got}"; then
        echo "FAIL: project hook did not run:" >&2; echo "${got}" >&2; return 1
    fi
}

main "$@"
