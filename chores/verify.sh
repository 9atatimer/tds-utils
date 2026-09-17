#!/usr/bin/env bash
# verify.sh -- the dist VERIFY hook for packages/chores.pkg: run the hermetic
# unit suite against the staged tree (tds-install execs "./chores/verify.sh"
# from the staging root with TDS_VERIFY_ROOT set).

set -euo pipefail

main() {
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    command -v uv >/dev/null 2>&1 || { echo "chores/verify.sh: uv not found" >&2; return 1; }
    (cd "${here}" && uv run --quiet --all-extras pytest -q tests/unit)
}

main "$@"
