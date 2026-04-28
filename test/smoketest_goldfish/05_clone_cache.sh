#!/usr/bin/env bash
# 05_clone_cache.sh — first run writes the cache, second run uses it (G3).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

main() {
    make_fake_clone "todd/cached" >/dev/null
    rm -rf "${SMOKE_CACHE}"
    run_goldfish >/dev/null 2>&1
    cache_file="${SMOKE_CACHE}/goldfish/clones.json"
    if [[ ! -f "${cache_file}" ]]; then
        echo "FAIL: cache file not written at ${cache_file}"
        return 1
    fi
    if ! grep -q "todd/cached" "${cache_file}"; then
        echo "FAIL: cache does not contain todd/cached:"
        cat "${cache_file}"
        return 1
    fi
    # Second run with cache present should still surface the repo.
    out="$(run_goldfish 2>&1)"
    if ! grep -q "todd/cached" <<<"${out}"; then
        echo "FAIL: cached run did not surface todd/cached:"
        echo "${out}"
        return 1
    fi
    if ! grep -q "using cached clones" <<<"${out}"; then
        echo "FAIL: stderr did not announce cache hit:"
        echo "${out}"
        return 1
    fi
}

main "$@"
