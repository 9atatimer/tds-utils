#!/usr/bin/env bash
# 01_local_clone_appears.sh — a fake clone with a github remote shows up in the table.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    make_fake_clone "todd/foo" >/dev/null
    out="$(run_goldfish 2>/dev/null)"
    if ! grep -q "todd/foo" <<<"${out}"; then
        echo "FAIL: todd/foo not in output:"
        echo "${out}"
        return 1
    fi
}

main "$@"
