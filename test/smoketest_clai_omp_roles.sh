#!/usr/bin/env bash
# smoketest_clai_omp_roles.sh -- clai.d/omp/pre/40-model-roles puts every
# omp role on a GitHub Copilot model (the owner's `omp login github-copilot`;
# no 1Password, no local inference, owner 2026-11-08): default on the strong
# model, the judging roles on the deep model, the bulk roles on the bulk
# model. It disables omp's local providers, removes the fallback chains an
# earlier version wrote (to the local model or to the Cloudflare gateway),
# leaves a hand-changed role and unrelated settings alone, and never blocks
# the launch.
#
# Hermetic: a fake `omp` (config in a JSON file) goes first on PATH, with a
# scratch HOME. No omp, no network.
#
# Usage: ./test/smoketest_clai_omp_roles.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
HOOK="${REPO_DIR}/clai.d/omp/pre/40-model-roles"

STRONG="github-copilot/kimi-k3"
DEEP="github-copilot/claude-opus-5.5"
BULK="github-copilot/claude-haiku-5.5"
OLD_LOCAL="ollama/omp-coder:latest"
OLD_KIMI="cf-workers-ai/@cf/moonshotai/kimi-k2.7-code"

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
    chmod +x "${SCRATCH}/bin/omp"
}

reset_state() {
    export FAKE_DIR="${SCRATCH}/state" HOME="${SCRATCH}/home"
    rm -rf "${FAKE_DIR}" "${HOME}"
    mkdir -p "${FAKE_DIR}" "${HOME}"
    unset CLAI_OMP_REFRESH CLAI_OMP_STRONG_MODEL CLAI_OMP_DEEP_MODEL CLAI_OMP_BULK_MODEL
}

run_hook() {
    PATH="${SCRATCH}/bin:${PATH}" "${HOOK}" 2>"${FAKE_DIR}/stderr"
}

cfg() { jq -c "$1" "${FAKE_DIR}/config.json"; }
role() { jq -r --arg r "$1" '.modelRoles[$r] // empty' "${FAKE_DIR}/config.json"; }
sets() { [[ -e "${FAKE_DIR}/omp.log" ]] && wc -l <"${FAKE_DIR}/omp.log" | tr -d ' ' || echo 0; }

# --- Tests ---

test_every_role_is_on_copilot() {
    reset_state
    echo '{"modelRoles": {"vision": "keep/me"}}' >"${FAKE_DIR}/config.json"
    run_hook || bad "hook exited non-zero"
    assert_eq "default" "${STRONG}" "$(role default)"
    local r
    for r in slow plan advisor; do assert_eq "role ${r}" "${DEEP}" "$(role "${r}")"; done
    for r in smol task commit tiny memory widget; do assert_eq "role ${r}" "${BULK}" "$(role "${r}")"; done
    assert_eq "an unmanaged role is kept" keep/me "$(role vision)"
    assert_eq "no setup wizard" true "$(cfg '."startup.setupWizard" == false')"
}

test_local_providers_are_disabled() {
    reset_state
    echo '{"disabledProviders": ["someone-else"]}' >"${FAKE_DIR}/config.json"
    run_hook
    local p
    for p in ollama llama.cpp lm-studio apple; do
        assert_eq "${p} disabled" true "$(jq --arg p "${p}" '.disabledProviders | index($p) != null' "${FAKE_DIR}/config.json")"
    done
    assert_eq "another disabled provider is kept" true "$(jq '.disabledProviders | index("someone-else") != null' "${FAKE_DIR}/config.json")"
}

test_old_fallbacks_are_removed() {
    reset_state
    jq -n --arg l "${OLD_LOCAL}" --arg k "${OLD_KIMI}" \
        '{modelRoles: {default: $k, smol: $l}, "retry.fallbackChains": {($k): [$l], "github-copilot/kimi-k2.7-code": [$l], ($STRONG): [$k], "other/m": ["x/y"]}}' \
        --arg STRONG "${STRONG}" >"${FAKE_DIR}/config.json"
    run_hook
    assert_eq "no chain falls back to local" "0" \
        "$(jq --arg l "${OLD_LOCAL}" '[."retry.fallbackChains" | to_entries[] | select(.value | index($l))] | length' "${FAKE_DIR}/config.json")"
    assert_eq "no chain falls back to the gateway" "0" \
        "$(jq --arg k "${OLD_KIMI}" '[."retry.fallbackChains" | to_entries[] | select(.value | index($k))] | length' "${FAKE_DIR}/config.json")"
    assert_eq "no chain is keyed on the gateway" "0" \
        "$(jq '[."retry.fallbackChains" | keys[] | select(startswith("cf-workers-ai/"))] | length' "${FAKE_DIR}/config.json")"
    assert_eq "another chain is kept" '["x/y"]' "$(jq -c '."retry.fallbackChains"["other/m"]' "${FAKE_DIR}/config.json")"
    assert_eq "smol leaves the local model" "${BULK}" "$(role smol)"
    assert_eq "default leaves the gateway" "${STRONG}" "$(role default)"
}

test_second_run_writes_nothing() {
    reset_state
    run_hook
    local before; before="$(sets)"
    run_hook
    assert_eq "no config writes on an unchanged run" "${before}" "$(sets)"
}

test_hand_changed_role_stays() {
    reset_state
    run_hook
    PATH="${SCRATCH}/bin:${PATH}" omp config set modelRoles '{"smol":"mine/model"}'
    run_hook
    assert_eq "a role changed by hand stays changed" mine/model "$(role smol)"
}

test_refresh_reapplies() {
    reset_state
    run_hook
    PATH="${SCRATCH}/bin:${PATH}" omp config set modelRoles '{"smol":"mine/model"}'
    CLAI_OMP_REFRESH=1 run_hook
    assert_eq "CLAI_OMP_REFRESH=1 reapplies" "${BULK}" "$(role smol)"
}

test_models_can_be_overridden() {
    reset_state
    CLAI_OMP_STRONG_MODEL=a/strong CLAI_OMP_DEEP_MODEL=a/deep CLAI_OMP_BULK_MODEL=a/bulk run_hook
    assert_eq "strong override" a/strong "$(role default)"
    assert_eq "deep override" a/deep "$(role plan)"
    assert_eq "bulk override" a/bulk "$(role task)"
}

test_no_omp_exits_zero() {
    reset_state
    PATH="/usr/bin:/bin" "${HOOK}" 2>/dev/null || bad "hook exited non-zero without omp"
    ok
}

# --- Main ---

main() {
    command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not found"; exit 0; }
    make_fakes
    test_every_role_is_on_copilot
    test_local_providers_are_disabled
    test_old_fallbacks_are_removed
    test_second_run_writes_nothing
    test_hand_changed_role_stays
    test_refresh_reapplies
    test_models_can_be_overridden
    test_no_omp_exits_zero
    echo "smoketest_clai_omp_roles: ${pass} passed, ${fail} failed"
    (( fail == 0 ))
}

main "$@"
