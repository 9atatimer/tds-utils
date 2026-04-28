#!/usr/bin/env bash
# 04_json_output.sh — --json emits a parseable JSON array (G5).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    make_fake_clone "todd/json" >/dev/null
    out="$(run_goldfish --json 2>/dev/null)"
    # Must parse as JSON.
    if ! python3 -c "import json,sys; json.loads(sys.stdin.read())" <<<"${out}" 2>/dev/null; then
        echo "FAIL: --json output is not valid JSON:"
        echo "${out}"
        return 1
    fi
    # Must contain the repo name.
    if ! python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
names = [r['name'] for r in data]
sys.exit(0 if 'todd/json' in names else 1)
" <<<"${out}"; then
        echo "FAIL: todd/json missing from JSON output:"
        echo "${out}"
        return 1
    fi
}

main "$@"
