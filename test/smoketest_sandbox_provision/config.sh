#!/usr/bin/env bash
# config.sh -- shared fixtures + helpers for the sandbox/provision.sh flow tests
#
# Network-free and hermetic. Each scenario STAGES a copy of sandbox/provision.sh
# next to a scenario-controlled pins.env, runs it with a fake $PATH whose `npm`
# and `clai` are stubs, and asserts the observable behavior (exit code, whether
# npm was invoked, whether `clai provision` ran and with what args, and the
# stderr log). No real npm, no real clai, no network, no real $HOME are ever
# touched.
#
# Sourcing this file is side-effect-free; run_all.sh allocates ${SMOKE_TMP} and
# each scenario calls `scenario_dir` to mint an isolated staging tree beneath it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# The script under test. Overridable so the suite can be aimed at a staged copy.
: "${PROVISION_SRC:=${REPO_DIR}/sandbox/provision.sh}"

# --- Guards ------------------------------------------------------------------

require_provision() {
    [[ -f "${PROVISION_SRC}" ]] || {
        echo "FAIL: script under test not found: ${PROVISION_SRC}"
        return 1
    }
}

# --- Staging -----------------------------------------------------------------

# scenario_dir <name> -- mint a fresh staging tree under SMOKE_TMP and echo its
# path. Layout: <dir>/provision.sh (copy), <dir>/pins.env (scenario-written),
# <dir>/bin (fake PATH front), <dir>/home (fake HOME), <dir>/prefix (CLAI_PREFIX),
# <dir>/record (provision-call log), <dir>/stderr (captured log).
scenario_dir() {
    if [[ -z "${SMOKE_TMP:-}" ]]; then
        echo "error: SMOKE_TMP must be set before scenario_dir" >&2
        return 1
    fi
    local dir
    dir="$(mktemp -d "${SMOKE_TMP}/${1}.XXXXXX")"
    cp "${PROVISION_SRC}" "${dir}/provision.sh"
    mkdir -p "${dir}/bin" "${dir}/home" "${dir}/prefix"
    printf '%s\n' "${dir}"
}

# write_pins <dir> <clai_version> -- write the scenario's pins.env. Pass the
# literal token UNSET to exercise the disarmed path.
write_pins() {
    local dir="$1" version="$2"
    cat > "${dir}/pins.env" <<EOF
CLAI_VERSION="${version}"
TEMPLATE_TOOLS_REPO="nine-at-a-time-media/template-tools"
AI_TOOLS_REPO="nine-at-a-time-media/template-tools"
EOF
}

# --- Stubs -------------------------------------------------------------------

# clai_stub_text <version> <record> -- emit (to stdout) a clai stub that reports
# <version> for `--version` and appends its provision args to <record>.
clai_stub_text() {
    local version="$1" record="$2"
    cat <<EOF
#!/usr/bin/env bash
if [ "\$1" = "--version" ]; then echo "clai ${version}"; exit 0; fi
if [ "\$1" = "provision" ]; then shift; printf '%s\n' "\$*" >> "${record}"; exit 0; fi
exit 0
EOF
}

# make_clai_stub <bindir> <version> <record> -- install a clai stub on the fake
# PATH (used for the "clai already present" scenarios).
make_clai_stub() {
    local bindir="$1" version="$2" record="$3"
    clai_stub_text "${version}" "${record}" > "${bindir}/clai"
    chmod +x "${bindir}/clai"
}

# make_npm_install_stub <bindir> <install_version> <record> -- a fake npm that,
# on `npm install --prefix DIR ...`, plants a clai stub of <install_version> at
# DIR/node_modules/.bin/clai (mimicking a successful GitHub Packages install).
make_npm_install_stub() {
    local bindir="$1" install_version="$2" record="$3" clai_b64
    clai_b64="$(clai_stub_text "${install_version}" "${record}" | base64 | tr -d '\n')"
    cat > "${bindir}/npm" <<EOF
#!/usr/bin/env bash
prefix=""
while [ \$# -gt 0 ]; do
  case "\$1" in --prefix) prefix="\$2"; shift 2 ;; *) shift ;; esac
done
[ -n "\$prefix" ] || exit 1
mkdir -p "\$prefix/node_modules/.bin"
printf '%s' '${clai_b64}' | base64 -d > "\$prefix/node_modules/.bin/clai"
chmod +x "\$prefix/node_modules/.bin/clai"
exit 0
EOF
    chmod +x "${bindir}/npm"
}

# make_npm_fail_stub <bindir> -- a fake npm that always fails (unreachable
# registry / bad token), planting nothing.
make_npm_fail_stub() {
    local bindir="$1"
    cat > "${bindir}/npm" <<'EOF'
#!/usr/bin/env bash
echo "npm ERR! stubbed failure" >&2
exit 1
EOF
    chmod +x "${bindir}/npm"
}

# make_npm_forbidden_stub <bindir> <marker> -- a fake npm that records the fact
# it was called (by creating <marker>) and no-ops. Lets a test assert npm was
# NOT invoked while keeping the run hermetic even if it wrongly were.
make_npm_forbidden_stub() {
    local bindir="$1" marker="$2"
    cat > "${bindir}/npm" <<EOF
#!/usr/bin/env bash
: > "${marker}"
exit 0
EOF
    chmod +x "${bindir}/npm"
}

# --- Runner ------------------------------------------------------------------

# run_provision <dir> -- run the staged provision.sh with a hermetic
# environment: fake PATH front (bin/), fake HOME, CLAI_PREFIX under the scenario
# dir, a fake token so write_npmrc proceeds. Captures stderr to <dir>/stderr and
# echoes the exit code. Never inherits the caller's real npm/clai.
run_provision() {
    local dir="$1" rc=0
    PATH="${dir}/bin:${PATH}" \
    HOME="${dir}/home" \
    CLAI_PREFIX="${dir}/prefix" \
    GH_AI_TOOLS_PAT="faketoken-readpackages" \
        bash "${dir}/provision.sh" >/dev/null 2>"${dir}/stderr" || rc=$?
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

assert_file_absent() {
    local f="$1" msg="$2"
    if [[ -e "${f}" ]]; then
        echo "FAIL: ${msg} (file exists: ${f})"
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

# assert_provisioned <dir> <expected_args> -- the staged run reached
# `clai provision <expected_args>` exactly once.
assert_provisioned() {
    local dir="$1" expected="$2" got
    if [[ ! -f "${dir}/record" ]]; then
        echo "FAIL: expected clai provision to run, but no record was written"
        echo "--- stderr ---"; cat "${dir}/stderr" 2>/dev/null
        return 1
    fi
    got="$(cat "${dir}/record")"
    assert_eq "${got}" "${expected}" "clai provision args"
}

assert_not_provisioned() {
    local dir="$1"
    if [[ -f "${dir}/record" ]]; then
        echo "FAIL: clai provision ran but should not have (args: $(cat "${dir}/record"))"
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

export -f require_provision scenario_dir write_pins \
    clai_stub_text make_clai_stub make_npm_install_stub make_npm_fail_stub \
    make_npm_forbidden_stub run_provision \
    assert_eq assert_file_absent assert_file_present \
    assert_provisioned assert_not_provisioned assert_stderr_contains
