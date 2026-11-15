#!/usr/bin/env bash
# smoketest_clai_codex_model.sh -- clai.d/codex/pre/30-model owns Codex's
# default model and reasoning effort in ~/.codex/config.toml: gpt-6.1-terra
# at medium, which also replaces any 5.x terra pin. It changes only those two
# top-level keys, leaves tables and comments alone, is idempotent, honours
# the override variables, and never blocks the launch.
#
# Hermetic: a scratch HOME with a fake config.toml; no codex, no network.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$(dirname "${SCRIPT_DIR}")/clai.d/codex/pre/30-model"
WORK=""
TESTS_RUN=0
TESTS_FAILED=0

# --- Action functions ---

cleanup() { [[ -n "${WORK}" && -d "${WORK}" ]] && rm -rf "${WORK}"; return 0; }

fail() {
    echo "FAIL: $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# make_home <name> <config-text> -- a scratch HOME with that config.toml.
make_home() {
    local home="${WORK}/$1"
    mkdir -p "${home}/.codex"
    printf '%s' "$2" >"${home}/.codex/config.toml"
    printf '%s\n' "${home}"
}

# run_hook <home> [VAR=value...] -- the way clai runs a pre-hook.
run_hook() {
    local home=$1
    shift
    env HOME="${home}" CLAI_AGENT=codex CLAI_STAGE=pre CLAI_CWD="${home}" "$@" "${HOOK}"
}

config() { cat "$1/.codex/config.toml"; }

# toml_get <home> <key> -- the top-level value, read with Python's TOML parser.
toml_get() {
    python3 -I - "$1/.codex/config.toml" "$2" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as fh:
    print(tomllib.load(fh).get(sys.argv[2], ""))
PY
}

# --- Flow functions ---

SAMPLE='# my codex config
model = "gpt-5.6-terra"
model_reasoning_effort = "high"
personality = "pragmatic"

[projects."/w/repo"]
trust_level = "trusted"

[profiles.fast]
model = "gpt-5.6-terra"
model_reasoning_effort = "low"
'

# Given a config pinning gpt-5.6-terra at high, When the hook runs as clai
# runs it, Then the top-level model is gpt-6.1-terra at medium, and the
# comment, other keys and every table (a profile's own model included) are
# unchanged, and the file still parses.
test_sets_the_default_and_leaves_the_rest() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home after
    home=$(make_home pinned "${SAMPLE}")
    run_hook "${home}" || fail "pinned: non-zero exit"
    [[ "$(toml_get "${home}" model)" == "gpt-6.1-terra" ]] || fail "pinned: model is $(toml_get "${home}" model)"
    [[ "$(toml_get "${home}" model_reasoning_effort)" == "medium" ]] \
        || fail "pinned: effort is $(toml_get "${home}" model_reasoning_effort)"
    after=$(config "${home}")
    grep -qxF '# my codex config' <<<"${after}" || fail "pinned: comment lost"
    grep -qxF 'personality = "pragmatic"' <<<"${after}" || fail "pinned: other key lost"
    grep -qxF '[profiles.fast]' <<<"${after}" || fail "pinned: table lost"
    grep -qxF 'model_reasoning_effort = "low"' <<<"${after}" || fail "pinned: a profile's key was changed"
    [[ "$(grep -c 'gpt-5.6-terra' <<<"${after}")" -eq 1 ]] || fail "pinned: profile model changed or top-level not"
}

# Given a config with no model keys, When the hook runs, Then it adds both at
# the top level, ahead of the first table.
test_adds_missing_keys_ahead_of_tables() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home first
    home=$(make_home bare $'[projects."/w/repo"]\ntrust_level = "trusted"\n')
    run_hook "${home}" || fail "bare: non-zero exit"
    [[ "$(toml_get "${home}" model)" == "gpt-6.1-terra" ]] || fail "bare: model missing"
    [[ "$(toml_get "${home}" model_reasoning_effort)" == "medium" ]] || fail "bare: effort missing"
    first=$(grep -n '^\[' "${home}/.codex/config.toml" | head -1 | cut -d: -f1)
    [[ "$(grep -n '^model = ' "${home}/.codex/config.toml" | cut -d: -f1)" -lt "${first}" ]] \
        || fail "bare: model added inside a table"
}

# Given a hook that already ran, When it runs again, Then the file does not
# change.
test_is_idempotent() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home before
    home=$(make_home twice "${SAMPLE}")
    run_hook "${home}"
    before=$(config "${home}")
    run_hook "${home}"
    [[ "$(config "${home}")" == "${before}" ]] || fail "twice: second run changed the file"
}

# Given the override variables, When the hook runs, Then it writes those.
test_honours_overrides() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home
    home=$(make_home override "${SAMPLE}")
    run_hook "${home}" CLAI_CODEX_MODEL=gpt-7-terra CLAI_CODEX_REASONING_EFFORT=high
    [[ "$(toml_get "${home}" model)" == "gpt-7-terra" ]] || fail "override: model"
    [[ "$(toml_get "${home}" model_reasoning_effort)" == "high" ]] || fail "override: effort"
}

# Given no config.toml, or one the hook cannot parse, When the hook runs,
# Then it exits 0 and writes nothing.
test_never_blocks_the_launch() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home rc=0
    home="${WORK}/none"
    mkdir -p "${home}"
    run_hook "${home}" || rc=$?
    [[ "${rc}" -eq 0 ]] || fail "no config: exit ${rc}, want 0"
    [[ ! -e "${home}/.codex/config.toml" ]] || fail "no config: created one"
    home=$(make_home broken $'model = "unterminated\n')
    rc=0
    run_hook "${home}" || rc=$?
    [[ "${rc}" -eq 0 ]] || fail "broken: exit ${rc}, want 0"
    [[ "$(config "${home}")" == $'model = "unterminated' ]] || fail "broken: file was changed"
}

# --- Main ---

main() {
    trap cleanup EXIT INT TERM HUP
    WORK=$(mktemp -d)
    test_sets_the_default_and_leaves_the_rest
    test_adds_missing_keys_ahead_of_tables
    test_is_idempotent
    test_honours_overrides
    test_never_blocks_the_launch
    if [[ "${TESTS_FAILED}" -gt 0 ]]; then
        echo "${TESTS_FAILED} failed check(s) in ${TESTS_RUN} tests"
        exit 1
    fi
    echo "PASS: ${TESTS_RUN} tests"
}

main "$@"
