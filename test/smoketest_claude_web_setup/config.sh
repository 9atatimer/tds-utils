#!/usr/bin/env bash
# config.sh -- shared fixtures + helpers for the claude-web setup.sh tests
#
# Network-free and hermetic. Post-Phase-C contract: setup.sh no longer installs
# or registers anything itself -- it DISCOVERS the checkout and hands off to
# `<root>/bin/lmde acquire --pins <root>/sandbox/pins.env`. So each scenario
# STAGES a copy of setup.sh in an isolated tree, plants one or more fixture
# CHECKOUTS whose `bin/lmde` is a RECORDING stub (or a failing stub), runs
# setup.sh with a fake $HOME and a confined scan path, and asserts the
# observable result: which argv `lmde acquire` was invoked with, that the PAT
# reached it, that setup.sh wrote no ~/.claude.json and no .npmrc, and the
# fail-open exit code. No real npm, no real lmde, no network, no real $HOME.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

: "${SETUP_SRC:=${REPO_DIR}/sandbox/claude-web/setup.sh}"

require_setup() {
    [[ -f "${SETUP_SRC}" ]] || { echo "FAIL: script under test not found: ${SETUP_SRC}"; return 1; }
}

# scenario_dir <name> -- mint a staging tree: <dir>/setup.sh (copy),
# <dir>/bin (fake PATH front), <dir>/home (fake HOME), <dir>/cwd (empty, no
# .mcp.json), <dir>/stderr.
scenario_dir() {
    if [[ -z "${SMOKE_TMP:-}" ]]; then echo "error: SMOKE_TMP must be set before scenario_dir" >&2; return 1; fi
    local dir
    dir="$(mktemp -d "${SMOKE_TMP}/${1}.XXXXXX")"
    cp "${SETUP_SRC}" "${dir}/setup.sh"
    mkdir -p "${dir}/bin" "${dir}/home" "${dir}/cwd"
    printf '%s\n' "${dir}"
}

# lmde_record <home> -- the path the recording bin/lmde stub appends to. One
# line per invocation: "INVOKE|argv=<...>|pat=<SET|UNSET>". Keyed on $HOME so
# every stub across every fixture checkout writes to the same, test-visible
# file (the stubs inherit the run's fake $HOME).
lmde_record() {
    printf '%s\n' "$1/.lmde-record"
}

# _plant_lmde <checkout_root> <mode> -- write bin/lmde into a fixture checkout.
# mode "record": append the invocation to $HOME/.lmde-record and exit 0.
# mode "fail":   append the invocation, then exit 1 (setup.sh must stay
#                fail-open and still exit 0).
_plant_lmde() {
    local root="$1" mode="$2" rc=0
    [[ "${mode}" == "fail" ]] && rc=1
    mkdir -p "${root}/bin"
    cat > "${root}/bin/lmde" <<EOF
#!/usr/bin/env bash
# recording lmde stub (mode=${mode})
rec="\${HOME}/.lmde-record"
pat=UNSET; [ -n "\${GH_AI_TOOLS_PAT:-}" ] && pat=SET
printf 'INVOKE|argv=%s|pat=%s\n' "\$*" "\${pat}" >> "\${rec}" 2>/dev/null || true
exit ${rc}
EOF
    chmod +x "${root}/bin/lmde"
}

# make_checkout <dir> [mode] -- a fixture that satisfies setup.sh's three-marker
# is_checkout() AND carries the Phase-C handoff surface: bin/lmde (recording
# stub by default; pass "fail" for the failing stub) and sandbox/pins.env.
make_checkout() {
    local root="$1" mode="${2:-record}"
    mkdir -p "${root}/sandbox/claude-web"
    cp "${SETUP_SRC}" "${root}/sandbox/claude-web/setup.sh"
    printf '#!/usr/bin/env bash\nexit 0\n' > "${root}/sandbox/provision.sh"
    printf '{ "mcpServers": {} }\n' > "${root}/.mcp.json"
    printf 'CLAI_VERSION="0.5.5"\nAST_MCP_VERSION="latest"\n' > "${root}/sandbox/pins.env"
    _plant_lmde "${root}" "${mode}"
    printf '%s\n' "${root}"
}

# write_claude_fixture <home> -- seed ~/.claude.json with content setup.sh must
# now leave BYTE-FOR-BYTE untouched (registration moved to clai provision).
write_claude_fixture() {
    local home="$1"
    cat > "${home}/.claude.json" <<'JSON'
{
  "numStartups": 7,
  "mcpServers": {
    "existing-other": { "command": "/usr/bin/other-mcp", "args": ["--foo"] }
  },
  "projects": {
    "/repo/a": { "disabledMcpServers": ["ast-mcp", "cloudflare"] },
    "/repo/b": { "disabledMcpServers": ["cloudflare"] }
  }
}
JSON
}

# run_setup <dir> -- run the staged setup.sh hermetically. Honors optional
# SETUP_CWD, SETUP_PROJECT_DIR and SETUP_SCAN_ROOTS overrides.
#
# PATH must NOT inherit the caller's: prepending leaves the developer's real
# tools reachable. Only the scenario's stubs and the standard system
# directories (/usr/bin:/bin) are visible. setup.sh invokes bin/lmde by its
# discovered ABSOLUTE path, so it does not need lmde on PATH.
#
# SETUP_SCAN_ROOTS defaults to EMPTY, not unset: the fallback scan must never
# walk the developer's real /home/*/* during a test. Tests that exercise
# discovery set it explicitly.
run_setup() {
    local dir="$1" rc=0 cwd="${SETUP_CWD:-$1/cwd}"
    ( cd "${cwd}" \
      && PATH="${dir}/bin:/usr/bin:/bin" \
         HOME="${dir}/home" \
         GH_AI_TOOLS_PAT="faketoken-readpackages" \
         CLAUDE_PROJECT_DIR="${SETUP_PROJECT_DIR:-}" \
         SETUP_SCAN_ROOTS="${SETUP_SCAN_ROOTS-}" \
         bash "${dir}/setup.sh" >/dev/null 2>"${dir}/stderr" ) || rc=$?
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
assert_files_identical() {
    cmp -s "$1" "$2" || { echo "FAIL: ${3}"; echo "  files differ: $1 vs $2"; return 1; }
}
assert_stderr_contains() {
    local dir="$1" needle="$2" msg="$3"
    grep -qF "${needle}" "${dir}/stderr" 2>/dev/null || { echo "FAIL: ${msg}"; echo "  want stderr: ${needle}"; echo "--- stderr ---"; cat "${dir}/stderr" 2>/dev/null; return 1; }
}
# assert_record_argv <recfile> <expected-argv> <msg> -- exactly one recorded
# invocation, and its argv matches.
assert_record_argv() {
    local rec="$1" want="$2" msg="$3" count got
    count="$(grep -c 'INVOKE|' "${rec}" 2>/dev/null || true)"
    count="${count:-0}"
    assert_eq "${count}" "1" "${msg} (want exactly one invocation)" || return 1
    got="$(sed -n 's/^INVOKE|argv=\(.*\)|pat=.*/\1/p' "${rec}" | head -n1)"
    assert_eq "${got}" "${want}" "${msg} (argv)" || return 1
}
# assert_record_pat <recfile> <SET|UNSET> <msg>
assert_record_pat() {
    local rec="$1" want="$2" msg="$3" got
    got="$(sed -n 's/^INVOKE|.*|pat=\(.*\)/\1/p' "${rec}" | head -n1)"
    assert_eq "${got}" "${want}" "${msg}" || return 1
}

export -f require_setup scenario_dir lmde_record _plant_lmde make_checkout \
    write_claude_fixture run_setup \
    assert_eq assert_file_present assert_file_absent assert_files_identical \
    assert_stderr_contains assert_record_argv assert_record_pat
