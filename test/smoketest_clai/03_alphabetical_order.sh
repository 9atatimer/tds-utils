#!/usr/bin/env bash
# 03_alphabetical_order.sh
# Given multiple pre-hooks with different basenames across levels, when clai
# runs, then they execute in alphabetical order by basename, irrespective of
# which level they live at.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    init_scenario "03_alpha"
    # 20- at global, 10- at project — alpha order should put 10- first.
    write_hook "${FAKE_HOME}" claude pre 20-second \
        $'#!/usr/bin/env bash\nprintf "20\\n" >> "${SENTINEL}"\n'
    local proj="${FAKE_HOME}/proj"
    write_hook "${proj}" claude pre 10-first \
        $'#!/usr/bin/env bash\nprintf "10\\n" >> "${SENTINEL}"\n'
    make_agent claude 0
    run_clai proj claude >/dev/null

    local got; got="$(cat "${SENTINEL}")"
    local expected=$'10\n20\nagent:claude args:'
    if [[ "${got}" != "${expected}" ]]; then
        echo "FAIL: order mismatch" >&2
        echo "expected:" >&2; echo "${expected}" >&2
        echo "got:" >&2; echo "${got}" >&2
        return 1
    fi
}

main "$@"
