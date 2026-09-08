#!/usr/bin/env bash
# config.sh -- shared fixtures + helpers for the `skills-drift-check` tests
#
# Hermetic and network-free: every scenario runs the real
# bin/skills-drift-check against a fake HOME (controls the installed
# stamp), a stubbed `lmde` on a fake PATH (controls the published
# version), and, where relevant, a REAL local git repo built from scratch
# (controls the local-repo source) -- git operations on a throwaway temp
# dir are local disk only, no network. No real HOME, no real registry.
#
# Sourcing this file is side-effect-free; run_all.sh allocates ${SMOKE_TMP}
# and each scenario calls `scenario_dir` to mint an isolated staging tree.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

: "${CHECK_BIN:=${REPO_DIR}/bin/skills-drift-check}"

# local_version's node invocation needs `node` reachable on the hermetic
# PATH run_check builds -- it deliberately excludes the caller's own PATH
# so a stray `lmde` on the developer's machine can't leak in, but that same
# narrowing silently dropped node too (a scenario asserting drift then
# "passed" for the wrong reason: the local source was skipped, not
# evaluated). Resolve once, from whatever node the suite's OWN shell
# already has.
NODE_DIR="$(dirname "$(command -v node 2>/dev/null || true)" 2>/dev/null || true)"

# --- Guards ------------------------------------------------------------------

require_check_bin() {
    [[ -x "${CHECK_BIN}" ]] || {
        echo "FAIL: skills-drift-check under test not found or not executable: ${CHECK_BIN}"
        return 1
    }
}

# --- Staging -----------------------------------------------------------------

# scenario_dir <name> -- mint a fresh staging tree under SMOKE_TMP and echo
# its path. Layout: <dir>/bin (fake PATH front, holds the lmde stub) and
# <dir>/home (fake HOME, holds the acquire state stamp).
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

# make_lmde_stub <path> <latest_or_empty> -- a fake `lmde` binary that
# answers `acquire --latest skills` with <latest_or_empty> (empty -> prints
# nothing and exits 1, modelling latest_run's own fail-open contract: no
# credential / registry unreachable). Any other invocation exits 1.
make_lmde_stub() {
    local path="$1" latest="$2"
    cat > "${path}" <<EOF
#!/usr/bin/env bash
if [ "\$1" = "acquire" ] && [ "\$2" = "--latest" ] && [ "\$3" = "skills" ]; then
    if [ -n "${latest}" ]; then
        printf '%s\n' "${latest}"
        exit 0
    fi
    exit 0
fi
exit 1
EOF
    chmod +x "${path}"
}

# seed_stamp <home> <version> -- plant the acquire state stamp for skills,
# mimicking a prior `lmde acquire`.
seed_stamp() {
    local home="$1" version="$2"
    mkdir -p "${home}/.local/state/tds-utils/acquire"
    printf '%s\n' "${version}" > "${home}/.local/state/tds-utils/acquire/skills.version"
}

# make_skills_repo <path> <n_commits> -- build a REAL git repo at <path>
# shaped like 9atatimer/Skills: a real copy of scripts/version.mjs (so
# `node scripts/version.mjs <count>` produces the exact version this repo's
# own CI would), plus <n_commits> commits each touching a distinct file
# under skills/ -- so `git rev-list --count HEAD -- skills agents
# mcp/manifest.json package.json scripts` is EXACTLY <n_commits>, and the
# resulting local version is deterministically `0.2.<n_commits>` (SERIES
# from the real scripts/version.mjs).
make_skills_repo() {
    local path="$1" n="$2" i
    mkdir -p "${path}/scripts" "${path}/skills" "${path}/agents" "${path}/mcp"
    cp "${REPO_DIR}/../9atatimer/Skills/scripts/version.mjs" "${path}/scripts/version.mjs" \
        2>/dev/null || write_version_mjs "${path}/scripts/version.mjs"
    printf '{}' > "${path}/mcp/manifest.json"
    printf '{"name":"skills"}' > "${path}/package.json"
    git -C "${path}" init -q -b main
    git -C "${path}" config user.email "test@example.com"
    git -C "${path}" config user.name "Test"
    git -C "${path}" add -A
    git -C "${path}" commit -q -m "scaffold"
    for i in $(seq 1 "${n}"); do
        printf 'skill %s\n' "${i}" > "${path}/skills/skill-${i}.md"
        git -C "${path}" add "skills/skill-${i}.md"
        git -C "${path}" commit -q -m "add skill ${i}"
    done
}

# write_version_mjs <dest> -- fallback if the real repo isn't checked out
# beside this one (CI runners, other machines): a minimal but behaviorally
# identical stand-in for 9atatimer/Skills' scripts/version.mjs (same
# SERIES, same `<series>.<count>` rule).
write_version_mjs() {
    local dest="$1"
    cat > "${dest}" <<'EOF'
const [, , count] = process.argv;
process.stdout.write(`0.2.${Number(count)}\n`);
EOF
}

# --- Runner ------------------------------------------------------------------

# run_check <dir> [--repo <path>] -- run the real skills-drift-check with a
# hermetic environment: fake HOME, fake PATH (the stubbed lmde only),
# LMDE_BIN pointed at the stub. Captures stdout/stderr to <dir>/{stdout,stderr}
# and echoes the exit code. SKILLS_REPO_PATH is exported only when --repo is
# given, so its absence exercises the "no local clone" path (not a
# nonexistent path override, which would still be exported and could shadow
# a real ~/workplace/9atatimer/Skills on the machine running the suite).
run_check() {
    local dir="$1"; shift || true
    local repo_path=""
    if [[ "${1:-}" == "--repo" ]]; then
        repo_path="$2"
    fi
    local rc=0
    local hermetic_path="${dir}/bin:${NODE_DIR}:/usr/bin:/bin"
    if [[ -n "${repo_path}" ]]; then
        env "PATH=${hermetic_path}" "HOME=${dir}/home" \
            "LMDE_BIN=${dir}/bin/lmde" "SKILLS_REPO_PATH=${repo_path}" \
            "${CHECK_BIN}" >"${dir}/stdout" 2>"${dir}/stderr" || rc=$?
    else
        env "PATH=${hermetic_path}" "HOME=${dir}/home" \
            "LMDE_BIN=${dir}/bin/lmde" \
            "${CHECK_BIN}" >"${dir}/stdout" 2>"${dir}/stderr" || rc=$?
    fi
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

assert_stdout_contains() {
    local dir="$1" needle="$2" msg="$3"
    if ! grep -qF "${needle}" "${dir}/stdout" 2>/dev/null; then
        echo "FAIL: ${msg}"
        echo "  expected stdout to contain: ${needle}"
        echo "--- stdout ---"; cat "${dir}/stdout" 2>/dev/null
        return 1
    fi
}

assert_stdout_empty() {
    local dir="$1" msg="$2"
    if [[ -s "${dir}/stdout" ]]; then
        echo "FAIL: ${msg}"
        echo "--- stdout (expected empty) ---"; cat "${dir}/stdout" 2>/dev/null
        return 1
    fi
}

assert_stderr_contains() {
    local dir="$1" needle="$2" msg="$3"
    if ! grep -qF "${needle}" "${dir}/stderr" 2>/dev/null; then
        echo "FAIL: ${msg}"
        echo "  expected stderr to contain: ${needle}"
        echo "--- stderr ---"; cat "${dir}/stderr" 2>/dev/null
        return 1
    fi
}

export -f require_check_bin scenario_dir make_lmde_stub seed_stamp \
    make_skills_repo write_version_mjs run_check \
    assert_eq assert_stdout_contains assert_stdout_empty assert_stderr_contains
