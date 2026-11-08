#!/usr/bin/env bash
# smoketest_clai_omp_cf_gateway.sh -- clai.d/omp/pre/30-cf-workers-ai is
# opt-in. By default omp runs on the owner's GitHub Copilot login: the hook
# never calls `op`, writes no provider, and removes the provider file it
# wrote before (marker-owned), leaving a hand-written one alone. With
# CLAI_OMP_CF_GATEWAY=1 it writes the Cloudflare gateway provider as before.
#
# Hermetic: fake `op` (logs every call) and `omp` go first on PATH, with a
# scratch HOME. No 1Password.
#
# Usage: ./test/smoketest_clai_omp_cf_gateway.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
HOOK="${REPO_DIR}/clai.d/omp/pre/30-cf-workers-ai"
MARKER="# managed by tds-utils clai.d/omp/pre/30-cf-workers-ai"

# --- Test harness ---

pass=0
fail=0

ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

# --- Fixtures ---

SCRATCH=""

cleanup() {
    [[ -n ${SCRATCH} ]] && rm -rf "${SCRATCH}"
}

make_fakes() {
    SCRATCH="$(mktemp -d)"
    trap cleanup EXIT
    mkdir -p "${SCRATCH}/bin"
    cat >"${SCRATCH}/bin/op" <<'SH'
#!/usr/bin/env bash
echo "op $*" >>"${FAKE_DIR}/op.log"
case "$*" in
    *base_url*) echo "https://example.invalid/ai/v1" ;;
    *gateway_id*) echo "personal" ;;
    *) exit 1 ;;
esac
SH
    cat >"${SCRATCH}/bin/omp" <<'SH'
#!/usr/bin/env bash
exit 0
SH
    chmod +x "${SCRATCH}/bin/op" "${SCRATCH}/bin/omp"
}

reset_state() {
    export FAKE_DIR="${SCRATCH}/state" HOME="${SCRATCH}/home"
    rm -rf "${FAKE_DIR}" "${HOME}"
    mkdir -p "${FAKE_DIR}" "${HOME}/.omp/agent"
    unset CLAI_OMP_CF_GATEWAY CLAI_OMP_REFRESH
}

run_hook() {
    PATH="${SCRATCH}/bin:${PATH}" "${HOOK}" 2>"${FAKE_DIR}/stderr"
}

models() { echo "${HOME}/.omp/agent/models.yml"; }
op_calls() { [[ -e "${FAKE_DIR}/op.log" ]] && wc -l <"${FAKE_DIR}/op.log" | tr -d ' ' || echo 0; }

# --- Tests ---

test_default_needs_no_1password() {
    reset_state
    run_hook || bad "hook exited non-zero"
    if [[ "$(op_calls)" == 0 ]]; then ok; else bad "op was called by default"; fi
    if [[ ! -e "$(models)" ]]; then ok; else bad "a provider file was written by default"; fi
}

test_default_removes_its_own_old_provider() {
    reset_state
    printf '%s\nproviders:\n  cf-workers-ai:\n    apiKey: "!op read x"\n' "${MARKER}" >"$(models)"
    run_hook || bad "hook exited non-zero"
    if [[ ! -e "$(models)" ]]; then ok; else bad "the hook's own provider file was left behind"; fi
    if [[ "$(op_calls)" == 0 ]]; then ok; else bad "op was called while removing"; fi
}

test_default_leaves_a_hand_written_file() {
    reset_state
    printf 'providers:\n  mine: {}\n' >"$(models)"
    run_hook || bad "hook exited non-zero"
    if grep -q 'mine' "$(models)"; then ok; else bad "a hand-written models.yml was changed"; fi
}

test_opt_in_writes_the_gateway() {
    reset_state
    CLAI_OMP_CF_GATEWAY=1 run_hook || bad "hook exited non-zero"
    if grep -qxF "${MARKER}" "$(models)" && grep -q 'cf-workers-ai:' "$(models)" \
        && grep -q 'baseUrl: https://example.invalid/ai/v1' "$(models)"; then ok
    else bad "opt-in did not write the gateway provider"; fi
    if grep -q "apiKey: \"!op read 'op://" "$(models)"; then ok; else bad "the key is not an op:// reference"; fi
}

# --- Main ---

main() {
    make_fakes
    test_default_needs_no_1password
    test_default_removes_its_own_old_provider
    test_default_leaves_a_hand_written_file
    test_opt_in_writes_the_gateway
    echo "smoketest_clai_omp_cf_gateway: ${pass} passed, ${fail} failed"
    (( fail == 0 ))
}

main "$@"
