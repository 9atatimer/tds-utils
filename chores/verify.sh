#!/usr/bin/env bash
# verify.sh -- the dist VERIFY hook for packages/chores.pkg: run the hermetic
# unit suite against the staged tree (tds-install execs "./chores/verify.sh"
# from the staging root with TDS_VERIFY_ROOT set).
#
# The environment goes in a throwaway directory, never the staged tree's own
# chores/.venv: a VERIFY must not leave a platform-specific venv (with the
# dev extras) inside every installed distribution.

set -euo pipefail

# Script-global so the EXIT trap can see it (a `local` is gone by then).
ENV_DIR=""

cleanup() {
    [ -n "${ENV_DIR}" ] && rm -rf "${ENV_DIR}"
    return 0
}

main() {
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    command -v uv >/dev/null 2>&1 || { echo "chores/verify.sh: uv not found" >&2; return 1; }
    ENV_DIR="$(mktemp -d "${TMPDIR:-/tmp}/chores-verify.XXXXXX")"
    trap cleanup EXIT
    (
        cd "${here}" \
            && UV_PROJECT_ENVIRONMENT="${ENV_DIR}" \
               uv run --quiet --all-extras pytest -q tests/unit
    )
}

main "$@"
