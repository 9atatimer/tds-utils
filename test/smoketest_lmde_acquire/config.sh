#!/usr/bin/env bash
# config.sh -- shared fixtures + helpers for the `lmde acquire` flow tests
#
# Network-free and hermetic. Each scenario mints a fake $HOME and a fake $PATH
# whose `npm` is a stub, runs the REAL bin/lmde acquire against them, and
# asserts the observable behavior (exit code, whether npm install ran and with
# what package@version, the created ~/.local/bin symlinks, the recorded state
# stamps, and the stderr log). No real npm, no real registry, no network, and
# no real $HOME are ever touched.
#
# Sourcing this file is side-effect-free; run_all.sh allocates ${SMOKE_TMP} and
# each scenario calls `scenario_dir` to mint an isolated staging tree beneath it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# The verb under test lives in the real bin/lmde (it sources lmde/lib/acquire.sh
# relative to its own path). Overridable so the suite can be aimed at a copy.
: "${LMDE_BIN:=${REPO_DIR}/bin/lmde}"

# --- Guards ------------------------------------------------------------------

require_lmde() {
    [[ -x "${LMDE_BIN}" ]] || {
        echo "FAIL: lmde under test not found or not executable: ${LMDE_BIN}"
        return 1
    }
}

# --- Staging -----------------------------------------------------------------

# scenario_dir <name> -- mint a fresh staging tree under SMOKE_TMP and echo its
# path. Layout: <dir>/bin (fake PATH front, holds the npm stub) and <dir>/home
# (fake HOME). acquire lands installs under home/.local/{bin,share,state}.
scenario_dir() {
    if [[ -z "${SMOKE_TMP:-}" ]]; then
        echo "error: SMOKE_TMP must be set before scenario_dir" >&2
        return 1
    fi
    local dir
    dir="$(mktemp -d "${SMOKE_TMP}/${1}.XXXXXX")"
    mkdir -p "${dir}/bin" "${dir}/home"
    printf '%s\n' "${dir}"
}

# --- Stubs -------------------------------------------------------------------

# make_npm_stub <bindir> <clai_latest> <astmcp_latest> <installlog> -- a fake
# npm that answers `npm view <name> version` with the matching latest and, on
# `npm install --prefix DIR ... <name>@<ver>`, plants an executable shim at
# DIR/node_modules/.bin/<bin> (bin = the unscoped package name) and appends
# "<name>@<ver>" to <installlog>. Mimics a reachable GitHub Packages registry.
make_npm_stub() {
    local bindir="$1" clai_latest="$2" astmcp_latest="$3" installlog="$4"
    cat > "${bindir}/npm" <<EOF
#!/usr/bin/env bash
sub="\$1"; shift || true
if [ "\$sub" = "view" ]; then
  name="\$1"
  case "\$name" in
    *ast-mcp) [ -n "${astmcp_latest}" ] && echo "${astmcp_latest}" || exit 1 ;;
    *clai)    [ -n "${clai_latest}" ] && echo "${clai_latest}" || exit 1 ;;
    *) exit 1 ;;
  esac
  exit 0
fi
if [ "\$sub" = "install" ]; then
  prefix=""; spec=""
  while [ \$# -gt 0 ]; do
    case "\$1" in
      --prefix) prefix="\$2"; shift 2 ;;
      --userconfig) shift 2 ;;
      -*) shift ;;
      *) spec="\$1"; shift ;;
    esac
  done
  [ -n "\$prefix" ] || exit 1
  [ -n "\$spec" ] || exit 1
  name="\${spec%@*}"; ver="\${spec##*@}"; bin="\${name##*/}"
  mkdir -p "\$prefix/node_modules/.bin"
  printf '#!/usr/bin/env bash\necho %s\n' "\$ver" > "\$prefix/node_modules/.bin/\$bin"
  chmod +x "\$prefix/node_modules/.bin/\$bin"
  printf '%s\n' "\$spec" >> "${installlog}"
  exit 0
fi
exit 0
EOF
    chmod +x "${bindir}/npm"
}

# make_npm_fail_stub <bindir> -- a fake npm where both `view` and `install`
# fail (unreachable registry / bad token), planting nothing.
make_npm_fail_stub() {
    local bindir="$1"
    cat > "${bindir}/npm" <<'EOF'
#!/usr/bin/env bash
echo "npm ERR! stubbed failure" >&2
exit 1
EOF
    chmod +x "${bindir}/npm"
}

# make_npm_forbidden_install_stub <bindir> <clai_latest> <astmcp_latest> <marker>
# -- a fake npm whose `view` succeeds (returns the given latests, so the
# up-to-date comparison can resolve) but whose `install` touches <marker> and
# plants nothing, letting a test assert install was NEVER reached.
make_npm_forbidden_install_stub() {
    local bindir="$1" clai_latest="$2" astmcp_latest="$3" marker="$4"
    cat > "${bindir}/npm" <<EOF
#!/usr/bin/env bash
sub="\$1"; shift || true
if [ "\$sub" = "view" ]; then
  name="\$1"
  case "\$name" in
    *ast-mcp) echo "${astmcp_latest}" ;;
    *clai)    echo "${clai_latest}" ;;
    *) exit 1 ;;
  esac
  exit 0
fi
if [ "\$sub" = "install" ]; then
  : > "${marker}"
  exit 0
fi
exit 0
EOF
    chmod +x "${bindir}/npm"
}

# seed_installed <home> <shortname> <bin> <version> -- mimic a prior acquire:
# plant the npm-prefix shim, the ~/.local/bin symlink pointing at it, and the
# state stamp. Echoes (to stdout) the prefix-shim path so a test can assert the
# symlink target is left intact.
seed_installed() {
    local home="$1" shortname="$2" bin="$3" version="$4"
    local prefix_bin="${home}/.local/share/tds-utils/acquire/_npm/node_modules/.bin/${bin}"
    mkdir -p "$(dirname "${prefix_bin}")"
    printf '#!/usr/bin/env bash\necho %s\n' "${version}" > "${prefix_bin}"
    chmod +x "${prefix_bin}"
    mkdir -p "${home}/.local/bin"
    ln -sfn "${prefix_bin}" "${home}/.local/bin/${bin}"
    mkdir -p "${home}/.local/state/tds-utils/acquire"
    printf '%s\n' "${version}" > "${home}/.local/state/tds-utils/acquire/${shortname}.version"
    printf '%s\n' "${prefix_bin}"
}

# --- Runner ------------------------------------------------------------------

# run_acquire <dir> [args...] -- run the real bin/lmde acquire with a hermetic
# environment: fake PATH (bin/ plus the system dirs the flow needs), fake HOME,
# and GH_AI_TOOLS_PAT defaulted to a fake token (set TEST_PAT="" to exercise the
# missing-token path). Captures stderr to <dir>/stderr and echoes the exit code.
#
# PATH must NOT inherit the caller's: a real `npm` (or `clai`) on the developer
# laptop would break the hermetic assumption. Only the scenario's own stubs and
# /usr/bin:/bin are visible.
run_acquire() {
    local dir="$1"; shift || true
    local rc=0
    PATH="${dir}/bin:/usr/bin:/bin" \
    HOME="${dir}/home" \
    GH_AI_TOOLS_PAT="${TEST_PAT-faketoken-readpackages}" \
        bash "${LMDE_BIN}" acquire "$@" >/dev/null 2>"${dir}/stderr" || rc=$?
    printf '%s\n' "${rc}"
}

# run_check <dir> [args...] -- like run_acquire but for `acquire --check`:
# captures the advisory report to <dir>/stdout (the drift lines) and warnings to
# <dir>/stderr, then echoes the exit code. Same hermetic env as run_acquire.
# stdout is a regular file here, so `[ -t 1 ]` is false and the report is plain
# (uncolored) -- assertions can match literal text.
run_check() {
    local dir="$1"; shift || true
    local rc=0
    PATH="${dir}/bin:/usr/bin:/bin" \
    HOME="${dir}/home" \
    GH_AI_TOOLS_PAT="${TEST_PAT-faketoken-readpackages}" \
        bash "${LMDE_BIN}" acquire --check "$@" >"${dir}/stdout" 2>"${dir}/stderr" || rc=$?
    printf '%s\n' "${rc}"
}

# --- Assertions --------------------------------------------------------------

assert_eq() {
    local got="$1" expected="$2" msg="$3"
    if [[ "${got}" != "${expected}" ]]; then
        echo "FAIL: ${msg}"
        echo "  expected: ${expected}"
        echo "  got:      ${got}"
        return 1
    fi
}

assert_file_present() {
    local f="$1" msg="$2"
    if [[ ! -e "${f}" ]]; then
        echo "FAIL: ${msg} (file missing: ${f})"
        return 1
    fi
}

assert_file_absent() {
    local f="$1" msg="$2"
    if [[ -e "${f}" ]]; then
        echo "FAIL: ${msg} (file exists: ${f})"
        return 1
    fi
}

# assert_symlink_to <link> <target> <msg> -- <link> is a symlink whose readlink
# target is exactly <target>.
assert_symlink_to() {
    local link="$1" target="$2" msg="$3"
    if [[ ! -L "${link}" ]]; then
        echo "FAIL: ${msg} (not a symlink: ${link})"
        return 1
    fi
    local got
    got="$(readlink "${link}")"
    if [[ "${got}" != "${target}" ]]; then
        echo "FAIL: ${msg}"
        echo "  expected link target: ${target}"
        echo "  got:                  ${got}"
        return 1
    fi
}

# assert_installed <installlog> <spec> <msg> -- <installlog> records a
# `npm install` of <spec> (e.g. @nine-at-a-time-media/clai@1.2.3).
assert_installed() {
    local installlog="$1" spec="$2" msg="$3"
    if ! grep -qF "${spec}" "${installlog}" 2>/dev/null; then
        echo "FAIL: ${msg}"
        echo "  expected install log to contain: ${spec}"
        echo "--- install log ---"; cat "${installlog}" 2>/dev/null
        return 1
    fi
}

# assert_not_installed <installlog> <spec> <msg> -- <installlog> does NOT record
# an install of <spec>. A missing log counts as not-installed.
assert_not_installed() {
    local installlog="$1" spec="$2" msg="$3"
    if grep -qF "${spec}" "${installlog}" 2>/dev/null; then
        echo "FAIL: ${msg}"
        echo "  install log unexpectedly contains: ${spec}"
        return 1
    fi
}

# assert_stderr_contains <dir> <needle> <msg>
assert_stderr_contains() {
    local dir="$1" needle="$2" msg="$3"
    if ! grep -qF "${needle}" "${dir}/stderr" 2>/dev/null; then
        echo "FAIL: ${msg}"
        echo "  expected stderr to contain: ${needle}"
        echo "--- stderr ---"; cat "${dir}/stderr" 2>/dev/null
        return 1
    fi
}

# assert_stdout_contains <dir> <needle> <msg>
assert_stdout_contains() {
    local dir="$1" needle="$2" msg="$3"
    if ! grep -qF "${needle}" "${dir}/stdout" 2>/dev/null; then
        echo "FAIL: ${msg}"
        echo "  expected stdout to contain: ${needle}"
        echo "--- stdout ---"; cat "${dir}/stdout" 2>/dev/null
        return 1
    fi
}

# assert_stdout_empty <dir> <msg> -- the advisory report printed nothing (every
# package current). A file of zero size, or absent, both count as empty.
assert_stdout_empty() {
    local dir="$1" msg="$2"
    if [[ -s "${dir}/stdout" ]]; then
        echo "FAIL: ${msg}"
        echo "--- stdout (expected empty) ---"; cat "${dir}/stdout" 2>/dev/null
        return 1
    fi
}

export -f require_lmde scenario_dir \
    make_npm_stub make_npm_fail_stub make_npm_forbidden_install_stub \
    seed_installed run_acquire run_check \
    assert_eq assert_file_present assert_file_absent assert_symlink_to \
    assert_installed assert_not_installed assert_stderr_contains \
    assert_stdout_contains assert_stdout_empty
