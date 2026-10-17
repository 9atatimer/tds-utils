#!/usr/bin/env bash
# run_all.sh -- `lmde acquire` delegates to the installed acquire engine
# (tds-utils#549). The engine itself, and its behavior suite, live in
# template-tools packages/naatm-sandbox; these cases cover only the handoff.
# Hermetic: a fake HOME, a fake PATH, and a fake naatm-sandbox that records
# its argv.
#
# Usage: ./test/smoketest_lmde_acquire_delegates/run_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LMDE_BIN="${REPO_DIR}/bin/lmde"

# --- Harness ---

TESTS_RUN=0
TESTS_FAILED=0
TMP=""

fail() { echo "  FAIL: $*"; return 1; }

# fake_engine <dir> <rc> -- a naatm-sandbox that appends its argv to
# <dir>/argv and exits <rc>.
fake_engine() {
    local dir="$1" rc="$2"
    mkdir -p "${dir}"
    printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s/argv"\nexit %s\n' "${dir}" "${rc}" \
        > "${dir}/naatm-sandbox"
    chmod +x "${dir}/naatm-sandbox"
}

# fake_installed_engine <home> <version> -- the layout npm leaves: a package
# dir carrying package.json and bin/naatm-sandbox.sh, and a ~/.local/bin
# symlink into it. The engine records its argv in <home>/argv.
fake_installed_engine() {
    local home="$1" version="$2" pkg
    pkg="${home}/.local/lib/node_modules/@nine-at-a-time-media/sandbox"
    mkdir -p "${pkg}/bin" "${home}/.local/bin"
    printf '{"name":"@nine-at-a-time-media/sandbox","version":"%s"}\n' "${version}" > "${pkg}/package.json"
    printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s/argv"\nexit 0\n' "${home}" > "${pkg}/bin/naatm-sandbox.sh"
    chmod +x "${pkg}/bin/naatm-sandbox.sh"
    ln -sfn "${pkg}/bin/naatm-sandbox.sh" "${home}/.local/bin/naatm-sandbox"
}

# run_lmde <home> <pathfront> [args...] -- run lmde acquire hermetically;
# stderr to <home>/stderr; echo the exit code.
run_lmde() {
    local home="$1" front="$2" rc=0
    shift 2
    env -i "HOME=${home}" "PATH=${front}:/usr/bin:/bin" \
        bash "${LMDE_BIN}" acquire "$@" >/dev/null 2>"${home}/stderr" || rc=$?
    printf '%s\n' "${rc}"
}

scenario() {
    local d
    d="$(mktemp -d "${TMP}/case.XXXXXX")"
    mkdir -p "${d}/home/.local/bin" "${d}/path"
    printf '%s\n' "${d}"
}

# --- Cases ---

case_passes_args_verbatim() {
    local d rc
    d="$(scenario)"
    fake_engine "${d}/home/.local/bin" 0
    rc="$(run_lmde "${d}/home" "${d}/path" --check --pins /x/pins.env)"
    [ "${rc}" = "0" ] || fail "exit ${rc}, want 0" || return 1
    [ "$(cat "${d}/home/.local/bin/argv")" = "acquire --check --pins /x/pins.env" ] \
        || fail "engine argv: $(cat "${d}/home/.local/bin/argv" 2>/dev/null)"
}

case_engine_exit_code_passes_through() {
    local d rc
    d="$(scenario)"
    fake_engine "${d}/home/.local/bin" 2
    rc="$(run_lmde "${d}/home" "${d}/path" --bogus)"
    [ "${rc}" = "2" ] || fail "exit ${rc}, want the engine's 2 (a usage error)"
}

case_prefers_local_bin_over_path() {
    local d rc
    d="$(scenario)"
    fake_engine "${d}/home/.local/bin" 0
    fake_engine "${d}/path" 0
    rc="$(run_lmde "${d}/home" "${d}/path")"
    [ "${rc}" = "0" ] || fail "exit ${rc}" || return 1
    [ -f "${d}/home/.local/bin/argv" ] || fail "~/.local/bin/naatm-sandbox not used" || return 1
    [ ! -f "${d}/path/argv" ] || fail "the PATH copy ran instead of ~/.local/bin's"
}

case_falls_back_to_path() {
    local d rc
    d="$(scenario)"
    fake_engine "${d}/path" 0
    rc="$(run_lmde "${d}/home" "${d}/path" --latest skills)"
    [ "${rc}" = "0" ] || fail "exit ${rc}" || return 1
    [ "$(cat "${d}/path/argv" 2>/dev/null)" = "acquire --latest skills" ] || fail "PATH engine not used"
}

case_no_engine_names_bootstrap_and_exits_0() {
    local d rc
    d="$(scenario)"
    rc="$(run_lmde "${d}/home" "${d}/path")"
    [ "${rc}" = "0" ] || fail "exit ${rc}, want 0 (fail-open)" || return 1
    grep -qF 'npx --yes --package @nine-at-a-time-media/sandbox@latest naatm-sandbox setup' "${d}/home/stderr" \
        || fail "stderr does not name the bootstrap: $(cat "${d}/home/stderr")"
}

# An engine from before the acquire verb (sandbox < 0.9.0) answers
# `acquire` with its usage and exit 0, and it has no row to update itself, so
# exec'ing it would leave the machine silently stale forever. lmde names the
# re-bootstrap instead.
case_old_engine_names_rebootstrap() {
    local d rc
    d="$(scenario)"
    fake_installed_engine "${d}/home" "0.8.0"
    rc="$(run_lmde "${d}/home" "${d}/path" --check)"
    [ "${rc}" = "0" ] || fail "exit ${rc}, want 0 (fail-open)" || return 1
    [ ! -f "${d}/home/argv" ] || fail "the pre-acquire engine was exec'd: $(cat "${d}/home/argv")" || return 1
    grep -qF 'npx --yes --package @nine-at-a-time-media/sandbox@latest naatm-sandbox setup' "${d}/home/stderr" \
        || fail "stderr does not name the re-bootstrap: $(cat "${d}/home/stderr")"
}

case_current_engine_is_used() {
    local d rc
    d="$(scenario)"
    fake_installed_engine "${d}/home" "0.9.0"
    rc="$(run_lmde "${d}/home" "${d}/path" --latest skills)"
    [ "${rc}" = "0" ] || fail "exit ${rc}" || return 1
    [ "$(cat "${d}/home/argv" 2>/dev/null)" = "acquire --latest skills" ] || fail "the 0.9.0 engine was not exec'd"
}

case_no_engine_copy_in_tds_utils() {
    [ ! -e "${REPO_DIR}/lmde/lib/acquire.sh" ] || fail "lmde/lib/acquire.sh still exists" || return 1
    [ ! -e "${REPO_DIR}/lmde/lib/pins.env" ] || fail "lmde/lib/pins.env still exists" || return 1
    ! grep -q 'lib/acquire.sh' "${LMDE_BIN}" || fail "bin/lmde still sources an engine"
}

# --- Main ---

main() {
    TMP="$(mktemp -d "${TMPDIR:-/tmp}/lmde-delegates.XXXXXX")"
    trap 'rm -rf "${TMP}"' EXIT
    local c
    for c in case_passes_args_verbatim case_engine_exit_code_passes_through \
             case_prefers_local_bin_over_path case_falls_back_to_path \
             case_no_engine_names_bootstrap_and_exits_0 case_old_engine_names_rebootstrap \
             case_current_engine_is_used case_no_engine_copy_in_tds_utils; do
        TESTS_RUN=$((TESTS_RUN + 1))
        if "${c}"; then echo "  PASS ${c}"; else echo "  FAIL ${c}"; TESTS_FAILED=$((TESTS_FAILED + 1)); fi
    done
    echo "${TESTS_RUN} run, $((TESTS_RUN - TESTS_FAILED)) passed, ${TESTS_FAILED} failed"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
