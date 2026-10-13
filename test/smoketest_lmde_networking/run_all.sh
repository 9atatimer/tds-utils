#!/usr/bin/env bash
# run_all.sh -- orchestrate the LMDE networking smoke tests. Hermetic: a
# fake Caddy admin API on a unix socket; no TCP, no Homebrew, no launchd.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
run=0; passed=0; failed=0
for script in "${SCRIPT_DIR}"/[0-9][0-9]_*.sh; do
    [[ -f "${script}" ]] || continue
    run=$((run + 1)); name="$(basename "${script}" .sh)"
    if out="$(bash "${script}" 2>&1)"; then printf '  %s ... PASS\n' "${name}"; passed=$((passed + 1))
    else printf '  %s ... FAIL\n' "${name}"; printf '%s\n' "${out}" | sed 's/^/      /'; failed=$((failed + 1)); fi
done
printf '\n%d run, %d passed, %d failed\n' "${run}" "${passed}" "${failed}"
[[ "${failed}" -eq 0 ]]
