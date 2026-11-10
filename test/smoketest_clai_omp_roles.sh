#!/usr/bin/env bash
# smoketest_clai_omp_roles.sh -- clai.d/omp/pre/40-model-roles puts omp's
# interactive roles on GitHub Copilot models (the owner's `omp login
# github-copilot`; no 1Password, owner 2026-11-08) and the task role --
# the one every code-changing sub-agent runs on -- on the laptop's local
# ollama, so sub-agent inference is free (owner 2026-11-09): default on
# the strong model, the judging roles on the deep model, the bulk roles
# on the bulk model. It keeps omp's other local providers disabled
# (ollama itself is now discovered, and is removed from the list if
# present), removes the fallback chains an earlier version wrote (to the
# local model or to the Cloudflare gateway), leaves a hand-changed role
# and unrelated settings alone, and never blocks the launch.
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
TASK="ollama/omp-coder:latest"
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
    unset CLAI_OMP_REFRESH CLAI_OMP_STRONG_MODEL CLAI_OMP_DEEP_MODEL CLAI_OMP_BULK_MODEL CLAI_OMP_TASK_MODEL
}

run_hook() {
    PATH="${SCRATCH}/bin:${PATH}" "${HOOK}" 2>"${FAKE_DIR}/stderr"
}

cfg() { jq -c "$1" "${FAKE_DIR}/config.json"; }
role() { jq -r --arg r "$1" '.modelRoles[$r] // empty' "${FAKE_DIR}/config.json"; }
sets() { [[ -e "${FAKE_DIR}/omp.log" ]] && wc -l <"${FAKE_DIR}/omp.log" | tr -d ' ' || echo 0; }

# --- Tests ---

test_roles_land_on_their_tiers() {
    reset_state
    echo '{"modelRoles": {"vision": "keep/me"}}' >"${FAKE_DIR}/config.json"
    run_hook || bad "hook exited non-zero"
    assert_eq "default" "${STRONG}" "$(role default)"
    local r
    for r in slow plan advisor; do assert_eq "role ${r}" "${DEEP}" "$(role "${r}")"; done
    for r in smol commit tiny memory widget; do assert_eq "role ${r}" "${BULK}" "$(role "${r}")"; done
    assert_eq "role task is the local model" "${TASK}" "$(role task)"
    assert_eq "an unmanaged role is kept" keep/me "$(role vision)"
    assert_eq "no setup wizard" true "$(cfg '."startup.setupWizard" == false')"
}

test_local_providers_disabled_but_ollama() {
    reset_state
    # ollama seeded in the list: the hook must REMOVE it (an earlier
    # version added it), not just stop adding it.
    echo '{"disabledProviders": ["someone-else", "ollama"]}' >"${FAKE_DIR}/config.json"
    run_hook
    local p
    for p in llama.cpp lm-studio apple; do
        assert_eq "${p} disabled" true "$(jq --arg p "${p}" '.disabledProviders | index($p) != null' "${FAKE_DIR}/config.json")"
    done
    assert_eq "ollama is discovered" true "$(jq '.disabledProviders | index("ollama") == null' "${FAKE_DIR}/config.json")"
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
    CLAI_OMP_STRONG_MODEL=a/strong CLAI_OMP_DEEP_MODEL=a/deep CLAI_OMP_BULK_MODEL=a/bulk CLAI_OMP_TASK_MODEL=a/task run_hook
    assert_eq "strong override" a/strong "$(role default)"
    assert_eq "deep override" a/deep "$(role plan)"
    assert_eq "bulk override" a/bulk "$(role smol)"
    assert_eq "task override" a/task "$(role task)"
}

test_no_omp_exits_zero() {
    reset_state
    PATH="/usr/bin:/bin" "${HOOK}" 2>/dev/null || bad "hook exited non-zero without omp"
    ok
}

# A setting corrupted into the wrong type must not be rewritten empty:
# the jq filter errors, the update must propagate that, and the hook as
# a whole still fails open.
test_type_error_leaves_setting_untouched() {
    reset_state
    echo '{"modelRoles": "oops"}' >"${FAKE_DIR}/config.json"
    local rc=0
    run_hook || rc=$?
    assert_eq "a wrong-typed setting is not rewritten" '"oops"' "$(cfg '.modelRoles')"
    assert_eq "the launch is never blocked" 0 "${rc}"
}

# The task role points at a local model; when ollama cannot show it, the
# hook says so at launch (shown, not routed around) and still exits 0.
test_warns_when_task_model_missing() {
    reset_state
    cat >"${SCRATCH}/bin/ollama" <<'SH'
#!/usr/bin/env bash
exit 1
SH
    chmod +x "${SCRATCH}/bin/ollama"
    run_hook
    assert_eq "warning names the model" 1 "$(grep -c "task role model ${TASK}" "${FAKE_DIR}/stderr")"
    assert_eq "roles still applied" "${TASK}" "$(role task)"
}

test_no_warning_when_task_model_present() {
    reset_state
    # show succeeds only for the bare model name: a hook that forgets to
    # strip the ollama/ provider prefix gets a warning here.
    cat >"${SCRATCH}/bin/ollama" <<'SH'
#!/usr/bin/env bash
[[ $1 == show && $2 == "omp-coder:latest" ]]
SH
    chmod +x "${SCRATCH}/bin/ollama"
    run_hook
    assert_eq "no warning when the model shows" 0 "$(grep -c 'task role model' "${FAKE_DIR}/stderr")"
}

# --- Main ---

main() {
    command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not found"; exit 0; }
    make_fakes
    test_roles_land_on_their_tiers
    test_local_providers_disabled_but_ollama
    test_old_fallbacks_are_removed
    test_second_run_writes_nothing
    test_hand_changed_role_stays
    test_refresh_reapplies
    test_models_can_be_overridden
    test_no_omp_exits_zero
    test_type_error_leaves_setting_untouched
    test_warns_when_task_model_missing
    test_no_warning_when_task_model_present
    echo "smoketest_clai_omp_roles: ${pass} passed, ${fail} failed"
    (( fail == 0 ))
}

main "$@"
