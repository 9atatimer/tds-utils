#!/usr/bin/env bash
# config.sh -- shared fixtures + helpers for the claude-web session-start.sh
# tests.
#
# Network-free and hermetic. Post-Phase-C contract: session-start.sh runs an
# OFFLINE, configure-only `clai provision --copy --report` when clai is on
# PATH, and skips (fail-open) otherwise. It no longer delegates to
# sandbox/provision.sh (that bootstrap-and-fetch is gone for claude-web). Each
# scenario stages a copy of session-start.sh in a faithful sandbox/claude-web/
# layout, optionally plants a recording clai stub on a fake PATH, and asserts:
# clai provision's argv, the fail-open skip, and that a sibling provision.sh is
# NEVER executed. No real clai, no network, no real $HOME.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

: "${SESSION_SRC:=${REPO_DIR}/sandbox/claude-web/session-start.sh}"

require_session() {
    [[ -f "${SESSION_SRC}" ]] || { echo "FAIL: script under test not found: ${SESSION_SRC}"; return 1; }
}

# scenario_dir <name> -- mint a staging tree that mirrors the real repo layout:
#   <dir>/sandbox/claude-web/session-start.sh   (copy under test)
#   <dir>/sandbox/provision.sh                  (marker stub -- must NOT run)
#   <dir>/bin                                   (fake PATH front)
#   <dir>/home                                  (fake HOME)
#   <dir>/cwd                                   (empty working dir)
#   <dir>/stderr
scenario_dir() {
    if [[ -z "${SMOKE_TMP:-}" ]]; then echo "error: SMOKE_TMP must be set before scenario_dir" >&2; return 1; fi
    local dir
    dir="$(mktemp -d "${SMOKE_TMP}/${1}.XXXXXX")"
    mkdir -p "${dir}/sandbox/claude-web" "${dir}/bin" "${dir}/home" "${dir}/cwd"
    cp "${SESSION_SRC}" "${dir}/sandbox/claude-web/session-start.sh"
    # A provision.sh in the position the OLD find_core() would have located
    # (sibling parent of the script). If session-start.sh ever delegates to it
    # again, this marker file appears -- the "never calls provision.sh" guard.
    cat > "${dir}/sandbox/provision.sh" <<EOF
#!/usr/bin/env bash
touch "$(dirname "${dir}/sandbox/provision.sh")/PROVISION_RAN"
exit 0
EOF
    chmod +x "${dir}/sandbox/provision.sh"
    printf '%s\n' "${dir}"
}

# provision_marker <dir> -- the path the sibling provision.sh writes iff it runs.
provision_marker() {
    printf '%s\n' "$1/sandbox/PROVISION_RAN"
}

# clai_record <home> -- the path the recording clai stub appends to.
clai_record() {
    printf '%s\n' "$1/.clai-record"
}

# make_clai_stub <bindir> -- a fake clai that records its argv (one line per
# invocation) to $HOME/.clai-record and exits 0.
make_clai_stub() {
    local bindir="$1"
    cat > "${bindir}/clai" <<'EOF'
#!/usr/bin/env bash
printf 'INVOKE|argv=%s\n' "$*" >> "${HOME}/.clai-record" 2>/dev/null || true
exit 0
EOF
    chmod +x "${bindir}/clai"
}

# run_session <dir> -- run the staged session-start.sh hermetically with a
# confined PATH (only the scenario's stubs plus /usr/bin:/bin) and a fake HOME.
# CLAUDE_PROJECT_DIR points at the staged checkout root (as a real hook sees).
run_session() {
    local dir="$1" rc=0 cwd="${SESSION_CWD:-$1/cwd}"
    ( cd "${cwd}" \
      && PATH="${dir}/bin:/usr/bin:/bin" \
         HOME="${dir}/home" \
         CLAUDE_PROJECT_DIR="${dir}" \
         bash "${dir}/sandbox/claude-web/session-start.sh" >/dev/null 2>"${dir}/stderr" ) || rc=$?
    printf '%s\n' "${rc}"
}

# --- Assertions --------------------------------------------------------------

assert_eq() {
    local got="$1" expected="$2" msg="$3"
    [[ "${got}" == "${expected}" ]] || { echo "FAIL: ${msg}"; echo "  expected: ${expected}"; echo "  got:      ${got}"; return 1; }
}
assert_file_present() {
    [[ -e "$1" ]] || { echo "FAIL: ${2} (missing: $1)"; return 1; }
}
assert_file_absent() {
    [[ ! -e "$1" ]] || { echo "FAIL: ${2} (exists: $1)"; return 1; }
}
assert_stderr_contains() {
    local dir="$1" needle="$2" msg="$3"
    grep -qF "${needle}" "${dir}/stderr" 2>/dev/null || { echo "FAIL: ${msg}"; echo "  want stderr: ${needle}"; echo "--- stderr ---"; cat "${dir}/stderr" 2>/dev/null; return 1; }
}
# assert_record_argv <recfile> <expected-argv> <msg> -- exactly one recorded
# invocation, argv matches.
assert_record_argv() {
    local rec="$1" want="$2" msg="$3" count got
    count="$(grep -c 'INVOKE|' "${rec}" 2>/dev/null || true)"
    count="${count:-0}"
    assert_eq "${count}" "1" "${msg} (want exactly one invocation)" || return 1
    got="$(sed -n 's/^INVOKE|argv=\(.*\)/\1/p' "${rec}" | head -n1)"
    assert_eq "${got}" "${want}" "${msg} (argv)" || return 1
}

export -f require_session scenario_dir provision_marker clai_record \
    make_clai_stub run_session \
    assert_eq assert_file_present assert_file_absent assert_stderr_contains \
    assert_record_argv
