#!/usr/bin/env bash
# smoketest_clai_omp_roles.sh -- clai.d/omp/pre/40-model-roles puts omp's
# bulk roles on a local Ollama model and its judging roles on Kimi, falls
# back to Kimi everywhere when no local model can be offered, leaves a
# hand-changed role alone, and never blocks the launch.
#
# Hermetic: fake `omp` (config in a JSON file) and fake `ollama` (models
# as files) go first on PATH, with a scratch HOME. No Ollama, no omp.
#
# Usage: ./test/smoketest_clai_omp_roles.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
HOOK="${REPO_DIR}/clai.d/omp/pre/40-model-roles"

KIMI="cf-workers-ai/@cf/moonshotai/kimi-k2.7-code"
LOCAL="ollama/omp-coder:latest"

# --- Test harness ---

pass=0
fail=0

ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

assert_eq() {
    if [[ "$2" == "$3" ]]; then ok; else bad "$1: expected [$2], got [$3]"; fi
}

# --- Fixtures ---

SCRATCH=""

cleanup() {
    [[ -n ${SCRATCH} ]] && rm -rf "${SCRATCH}"
}

make_fakes() {
    SCRATCH="$(mktemp -d)"
    trap cleanup EXIT
    mkdir -p "${SCRATCH}/bin"

    # omp: `config get KEY --json` and `config set KEY VALUE` over a JSON
    # file of flat keys; every set is logged.
    cat >"${SCRATCH}/bin/omp" <<'SH'
#!/usr/bin/env bash
[[ $1 == config ]] || exit 9
cfg="${FAKE_DIR}/config.json"
[[ -s $cfg ]] || echo '{}' >"$cfg"
case $2 in
    get) jq --arg k "$3" '{key: $k, value: .[$k]}' "$cfg" ;;
    set)
        echo "set $3" >>"${FAKE_DIR}/omp.log"
        if v=$(jq -c . <<<"$4" 2>/dev/null); then :; else v=$(jq -nc --arg s "$4" '$s'); fi
        jq --arg k "$3" --argjson v "$v" '.[$k] = $v' "$cfg" >"$cfg.tmp" && mv "$cfg.tmp" "$cfg"
        ;;
    *) exit 9 ;;
esac
SH

    # ollama: a model is a file under models/ holding its num_ctx.
    cat >"${SCRATCH}/bin/ollama" <<'SH'
#!/usr/bin/env bash
m="${FAKE_DIR}/models"
case $1 in
    show)
        if [[ $2 == --parameters ]]; then
            [[ -e "$m/$3" ]] || exit 1
            ctx=$(cat "$m/$3"); [[ -z $ctx ]] || echo "num_ctx                        $ctx"
        else
            [[ -e "$m/$2" ]]
        fi
        ;;
    create)
        echo "create $2" >>"${FAKE_DIR}/ollama.log"
        [[ -z ${FAKE_CREATE_FAIL:-} ]] || exit 1
        awk '$1 == "PARAMETER" && $2 == "num_ctx" { print $3 }' "$4" >"$m/$2"
        ;;
    *) exit 9 ;;
esac
SH
    chmod +x "${SCRATCH}/bin/omp" "${SCRATCH}/bin/ollama"
}

# A fresh HOME and fake state; $1 names the models already pulled.
reset_state() {
    export FAKE_DIR="${SCRATCH}/state" HOME="${SCRATCH}/home"
    rm -rf "${FAKE_DIR}" "${HOME}"
    mkdir -p "${FAKE_DIR}/models" "${HOME}"
    local name
    for name in "$@"; do : >"${FAKE_DIR}/models/${name}"; done
    unset FAKE_CREATE_FAIL CLAI_OMP_REFRESH
}

run_hook() {
    PATH="${SCRATCH}/bin:${PATH}" "${HOOK}" 2>"${FAKE_DIR}/stderr"
}

role() { jq -r --arg r "$1" '.modelRoles[$r] // empty' "${FAKE_DIR}/config.json"; }
chain() { jq -c --arg k "${KIMI}" '."retry.fallbackChains"[$k] // empty' "${FAKE_DIR}/config.json"; }
sets() { [[ -e "${FAKE_DIR}/omp.log" ]] && wc -l <"${FAKE_DIR}/omp.log" | tr -d ' ' || echo 0; }

# --- Tests ---

test_local_model_takes_the_bulk_roles() {
    reset_state qwen3-coder:30b
    echo '{"modelRoles": {"vision": "keep/me"}}' >"${FAKE_DIR}/config.json"
    run_hook || bad "hook exited non-zero"
    assert_eq "variant built with num_ctx" 65536 "$(cat "${FAKE_DIR}/models/omp-coder")"
    local r
    for r in smol task commit tiny memory widget; do assert_eq "role ${r}" "${LOCAL}" "$(role "${r}")"; done
    for r in default slow plan advisor; do assert_eq "role ${r}" "${KIMI}" "$(role "${r}")"; done
    assert_eq "an unmanaged role is kept" keep/me "$(role vision)"
    assert_eq "Kimi falls back to local" "[\"${LOCAL}\"]" "$(chain)"
}

test_second_run_writes_nothing() {
    reset_state qwen3-coder:30b
    run_hook
    local before; before="$(sets)"
    run_hook
    assert_eq "no config writes on an unchanged run" "${before}" "$(sets)"
    assert_eq "no rebuild of a current variant" 1 "$(wc -l <"${FAKE_DIR}/ollama.log" | tr -d ' ')"
}

test_hand_changed_role_stays() {
    reset_state qwen3-coder:30b
    run_hook
    PATH="${SCRATCH}/bin:${PATH}" omp config set modelRoles '{"smol":"mine/model"}'
    run_hook
    assert_eq "a role changed by hand stays changed" mine/model "$(role smol)"
}

test_refresh_reapplies() {
    reset_state qwen3-coder:30b
    run_hook
    PATH="${SCRATCH}/bin:${PATH}" omp config set modelRoles '{"smol":"mine/model"}'
    CLAI_OMP_REFRESH=1 run_hook
    assert_eq "CLAI_OMP_REFRESH=1 reapplies" "${LOCAL}" "$(role smol)"
}

test_missing_base_keeps_every_role_on_kimi() {
    reset_state
    run_hook || bad "hook exited non-zero"
    assert_eq "smol on Kimi without a local model" "${KIMI}" "$(role smol)"
    assert_eq "task on Kimi without a local model" "${KIMI}" "$(role task)"
    assert_eq "no fallback without a local model" "" "$(chain)"
    if grep -q 'ollama pull qwen3-coder:30b' "${FAKE_DIR}/stderr"; then ok; else bad "no pull hint"; fi
}

test_pulling_later_moves_the_roles() {
    reset_state
    run_hook
    : >"${FAKE_DIR}/models/qwen3-coder:30b"
    run_hook
    assert_eq "roles move once the base is pulled" "${LOCAL}" "$(role smol)"
}

test_failed_build_keeps_kimi_and_exits_zero() {
    reset_state qwen3-coder:30b
    export FAKE_CREATE_FAIL=1
    run_hook || bad "hook exited non-zero on a failed build"
    assert_eq "task on Kimi after a failed build" "${KIMI}" "$(role task)"
}

test_stale_ctx_rebuilds() {
    reset_state qwen3-coder:30b
    echo 4096 >"${FAKE_DIR}/models/omp-coder"
    run_hook
    assert_eq "a variant with another num_ctx is rebuilt" 65536 "$(cat "${FAKE_DIR}/models/omp-coder")"
}

test_no_omp_exits_zero() {
    reset_state qwen3-coder:30b
    PATH="/usr/bin:/bin" "${HOOK}" 2>/dev/null || bad "hook exited non-zero without omp"
    ok
}

# --- Main ---

main() {
    command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not found"; exit 0; }
    make_fakes
    test_local_model_takes_the_bulk_roles
    test_second_run_writes_nothing
    test_hand_changed_role_stays
    test_refresh_reapplies
    test_missing_base_keeps_every_role_on_kimi
    test_pulling_later_moves_the_roles
    test_failed_build_keeps_kimi_and_exits_zero
    test_stale_ctx_rebuilds
    test_no_omp_exits_zero
    echo "smoketest_clai_omp_roles: ${pass} passed, ${fail} failed"
    (( fail == 0 ))
}

main "$@"
