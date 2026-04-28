#!/usr/bin/env bash
# 02_dirty_repo_marker.sh — a clone with uncommitted changes shows the dirty marker.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    dir="$(make_fake_clone "todd/dirty")"
    echo "untracked" > "${dir}/new_file.txt"
    out="$(run_goldfish 2>/dev/null)"
    line="$(grep "todd/dirty" <<<"${out}" || true)"
    if [[ -z "${line}" ]]; then
        echo "FAIL: todd/dirty not in output"
        echo "${out}"
        return 1
    fi
    if ! grep -q "\*" <<<"${line}"; then
        echo "FAIL: dirty marker '*' missing from row:"
        echo "${line}"
        return 1
    fi
}

main "$@"
