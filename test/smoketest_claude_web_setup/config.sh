#!/usr/bin/env bash
# config.sh -- shared fixtures + helpers for the claude-web setup.sh tests
#
# Network-free and hermetic. Each scenario STAGES a copy of
# sandbox/claude-web/setup.sh in an isolated tree, runs it with a fake $HOME
# and a fake $PATH whose `npm` is a stub that plants an ast-mcp bin (global or
# project-local), and asserts the observable result: the ast-mcp bin exists and
# ~/.claude.json registers it at the canonical user-scope path, preserving
# unrelated config and clearing ast-mcp from disabledMcpServers. No real npm, no
# network, no real $HOME.
#
# The staged copy has NO sibling provision.sh and each run uses an empty cwd +
# unset CLAUDE_PROJECT_DIR, so the clai-provision delegation is skipped (it logs
# "not found" and returns) and the project-scope pre-install only runs when a
# scenario explicitly points CLAUDE_PROJECT_DIR at a fixture checkout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

: "${SETUP_SRC:=${REPO_DIR}/sandbox/claude-web/setup.sh}"

require_setup() {
    [[ -f "${SETUP_SRC}" ]] || { echo "FAIL: script under test not found: ${SETUP_SRC}"; return 1; }
}
require_python3() {
    command -v python3 >/dev/null 2>&1 || { echo "skip: python3 not on PATH (setup.sh registration relies on it)" >&2; return 1; }
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

# make_npm_stub <bindir> -- a fake npm that honors `npm install [-g] --prefix
# DIR ...` by planting an executable ast-mcp stub at DIR/bin/ast-mcp (global)
# or DIR/node_modules/.bin/ast-mcp (local).
make_npm_stub() {
    local bindir="$1"
    cat > "${bindir}/npm" <<'EOF'
#!/usr/bin/env bash
prefix=""; global=""
while [ $# -gt 0 ]; do
  case "$1" in
    -g) global=1; shift ;;
    --prefix) prefix="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "$prefix" ] || exit 1
if [ -n "$global" ]; then
  target="$prefix/bin/ast-mcp"
else
  target="$prefix/node_modules/.bin/ast-mcp"
fi
mkdir -p "$(dirname "$target")"
printf '#!/usr/bin/env bash\necho "AST-MCP Server running on stdio"\n' > "$target"
chmod +x "$target"
exit 0
EOF
    chmod +x "${bindir}/npm"
}

# make_npm_fail_stub <bindir> -- a fake npm that always fails.
make_npm_fail_stub() {
    local bindir="$1"
    printf '#!/usr/bin/env bash\necho "npm ERR! stubbed failure" >&2\nexit 1\n' > "${bindir}/npm"
    chmod +x "${bindir}/npm"
}

# write_claude_fixture <home> -- seed ~/.claude.json with an unrelated mcp
# server, an unrelated top-level key, and projects that (wrongly) disable
# ast-mcp for setup.sh to fix.
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

# make_npm_dangling_stub <bindir> -- an npm that FAILS after leaving a broken
# bin symlink behind, exactly as a real interrupted `npm install -g` does
# (issue #113). setup.sh must remove it: the committed .mcp.json spawns that
# path, so a dangling link is worse than nothing.
make_npm_dangling_stub() {
    local bindir="$1"
    cat > "${bindir}/npm" <<'EOF'
#!/usr/bin/env bash
prefix=""
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) prefix="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "$prefix" ] || exit 1
mkdir -p "$prefix/bin"
ln -sf "../lib/node_modules/@nine-at-a-time-media/ast-mcp/dist/index.js" "$prefix/bin/ast-mcp"
echo "npm ERR! stubbed failure after linking" >&2
exit 1
EOF
    chmod +x "${bindir}/npm"
}

# make_checkout <dir> -- a fixture that satisfies setup.sh's three-marker
# is_checkout(): sandbox/claude-web/setup.sh + sandbox/provision.sh + .mcp.json.
make_checkout() {
    local root="$1"
    mkdir -p "${root}/sandbox/claude-web"
    cp "${SETUP_SRC}" "${root}/sandbox/claude-web/setup.sh"
    printf '#!/usr/bin/env bash\nexit 0\n' > "${root}/sandbox/provision.sh"
    printf '{ "mcpServers": {} }\n' > "${root}/.mcp.json"
    printf '%s\n' "${root}"
}

# run_setup <dir> -- run the staged setup.sh hermetically. Honors optional
# SETUP_CWD, SETUP_PROJECT_DIR and SETUP_SCAN_ROOTS overrides.
#
# PATH must NOT inherit the caller's: prepending leaves the developer's real
# npm/node reachable, so a "stubbed npm" scenario silently becomes a "real npm"
# scenario. Only the scenario's stubs and the system dirs setup.sh needs
# (python3, grep, sort, rm, mkdir) are visible.
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

# --- Assertions (python3-backed JSON queries) --------------------------------

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

# json_query <file> <python-expr over `d`> -- print the value, or "<none>".
json_query() {
    JQ_FILE="$1" python3 - "$2" <<'PY'
import json, os, sys
expr = sys.argv[1]
try:
    with open(os.environ["JQ_FILE"]) as f:
        d = json.load(f)
except Exception as e:
    print("<error:%s>" % e); sys.exit(0)
try:
    v = eval(expr, {"d": d})
except Exception:
    print("<none>"); sys.exit(0)
print(v if v is not None else "<none>")
PY
}

assert_json_eq() {
    local file="$1" expr="$2" expected="$3" msg="$4" got
    got="$(json_query "${file}" "${expr}")"
    assert_eq "${got}" "${expected}" "${msg}"
}
assert_stderr_contains() {
    local dir="$1" needle="$2" msg="$3"
    grep -qF "${needle}" "${dir}/stderr" 2>/dev/null || { echo "FAIL: ${msg}"; echo "  want stderr: ${needle}"; echo "--- stderr ---"; cat "${dir}/stderr" 2>/dev/null; return 1; }
}

export -f require_setup require_python3 scenario_dir make_npm_stub \
    make_npm_fail_stub make_npm_dangling_stub make_checkout \
    write_claude_fixture run_setup \
    assert_eq assert_file_present assert_file_absent json_query \
    assert_json_eq assert_stderr_contains
