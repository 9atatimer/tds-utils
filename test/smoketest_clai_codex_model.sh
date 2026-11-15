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

# Given a top-level multi-line string whose lines look like a key and a
# table header, When the hook runs, Then the string's value is unchanged and
# the top-level model is set.
test_never_edits_inside_a_multi_line_string() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home text
    text=$'instructions = """\nmodel = "q"\n[notes]\n"""\nmodel = "gpt-5.6-terra"\n\n[t]\na = 1\n'
    home=$(make_home mls "${text}")
    run_hook "${home}" 2>/dev/null
    # $(...) drops the string's trailing newline, so compare without it.
    [[ "$(toml_get "${home}" instructions)" == $'model = "q"\n[notes]' ]] || fail "mls: the string changed"
    [[ "$(toml_get "${home}" model)" == "gpt-6.1-terra" ]] || fail "mls: model is $(toml_get "${home}" model)"
}

# Given a quoted model key and an array whose lines start with "[", When the
# hook runs, Then it sets the model and the array is unchanged.
test_handles_quoted_keys_and_nested_arrays() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home
    home=$(make_home quoted $'"model" = "gpt-5.6-terra"\nx = [\n  ["a"],\n]\n\n[t]\na = 1\n')
    run_hook "${home}" 2>/dev/null
    [[ "$(toml_get "${home}" model)" == "gpt-6.1-terra" ]] || fail "quoted: model is $(toml_get "${home}" model)"
    [[ "$(toml_get "${home}" x)" == "[['a']]" ]] || fail "quoted: array is $(toml_get "${home}" x)"
}

# Given config.toml is a symlink to a file elsewhere, When the hook runs,
# Then the target is edited, the link stays a link, and the mode is kept.
test_edits_through_a_symlink_and_keeps_the_mode() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home target
    home="${WORK}/link"
    mkdir -p "${home}/.codex" "${WORK}/dotfiles"
    target="${WORK}/dotfiles/codex.toml"
    printf 'model = "gpt-5.6-terra"\n' >"${target}"
    chmod 644 "${target}"
    ln -s "${target}" "${home}/.codex/config.toml"
    run_hook "${home}" 2>/dev/null
    [[ -L "${home}/.codex/config.toml" ]] || fail "link: no longer a symlink"
    grep -q 'gpt-6.1-terra' "${target}" || fail "link: target not edited"
    [[ -n "$(find "${target}" -perm 644)" ]] || fail "link: mode changed"
}

# Given an override value that would inject TOML, When the hook runs, Then
# it changes nothing.
test_refuses_an_unsafe_override() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home before
    home=$(make_home inject "${SAMPLE}")
    before=$(config "${home}")
    run_hook "${home}" CLAI_CODEX_MODEL=$'x"\nsandbox_mode = "danger-full-access' 2>/dev/null
    [[ "$(config "${home}")" == "${before}" ]] || fail "inject: the file changed"
}

# Given HOME is unset, When the hook runs, Then it exits 0.
test_unset_home_never_blocks() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local rc=0
    env -u HOME CLAI_AGENT=codex "${HOOK}" 2>/dev/null || rc=$?
    [[ "${rc}" -eq 0 ]] || fail "no HOME: exit ${rc}, want 0"
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
    test_never_edits_inside_a_multi_line_string
    test_handles_quoted_keys_and_nested_arrays
    test_edits_through_a_symlink_and_keeps_the_mode
    test_refuses_an_unsafe_override
    test_unset_home_never_blocks
    if [[ "${TESTS_FAILED}" -gt 0 ]]; then
        echo "${TESTS_FAILED} failed check(s) in ${TESTS_RUN} tests"
        exit 1
    fi
    echo "PASS: ${TESTS_RUN} tests"
}

main "$@"
