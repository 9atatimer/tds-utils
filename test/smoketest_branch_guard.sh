#!/usr/bin/env bash
# smoketest_branch_guard.sh — behavioral smoke test for bin/branch-merged-check
# and the git-hooks/template/hooks/pre-commit branch-reuse guard.
#
# Hermetic: no network, no sleeps, no real gh. The PR state is injected via a
# tiny fake query fixture pointed at by TDS_BRANCHGUARD_QUERY, and the hook is
# pointed at the REAL checker via git config branchguard.checkerPath. Fixtures
# are throwaway temp git repos; the pre-commit hook is copied into each repo's
# .git/hooks (core.hooksPath is deliberately left unset).
#
# Usage: ./test/smoketest_branch_guard.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
CHECKER="${REPO_DIR}/bin/branch-merged-check"
PRE_COMMIT="${REPO_DIR}/git-hooks/template/hooks/pre-commit"

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1" condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

setup()   { WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/branch-guard-test.XXXXXX")"; }
cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixtures ---

# Write a fake TDS_BRANCHGUARD_QUERY script. It ignores its BRANCH arg and emits
# a canned "STATE NUMBER URL" line (or exits non-zero to simulate undetermined).
make_query() {
    local path="$1" kind="$2"
    case "${kind}" in
        merged) cat > "${path}" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "MERGED 123 https://github.com/o/r/pull/123"
EOF
            ;;
        closed) cat > "${path}" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "CLOSED 45 https://github.com/o/r/pull/45"
EOF
            ;;
        open) cat > "${path}" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "OPEN 7 https://github.com/o/r/pull/7"
EOF
            ;;
        empty) cat > "${path}" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
            ;;
        fail) cat > "${path}" <<'EOF'
#!/usr/bin/env bash
exit 3
EOF
            ;;
    esac
    chmod +x "${path}"
}

# A real git repo with an initial commit and inert commit config.
new_git_repo() {
    local dir="${WORKROOT}/$1"
    mkdir -p "${dir}"
    git -C "${dir}" init -q
    git -C "${dir}" config user.email t@t
    git -C "${dir}" config user.name t
    git -C "${dir}" config commit.gpgsign false
    printf 'x\n' > "${dir}/README.md"
    git -C "${dir}" add -A
    git -C "${dir}" commit -qm init
    printf '%s' "${dir}"
}

# A git repo with the real pre-commit hook copied in and pointed at the real
# checker via config. core.hooksPath is intentionally NOT set.
new_guarded_repo() {
    local dir
    dir="$(new_git_repo "$1")"
    cp "${PRE_COMMIT}" "${dir}/.git/hooks/pre-commit"
    chmod +x "${dir}/.git/hooks/pre-commit"
    git -C "${dir}" config branchguard.checkerPath "${CHECKER}"
    printf '%s' "${dir}"
}

head_of() { git -C "$1" rev-parse HEAD; }

# Stage a change and attempt a commit with the given query injected. Extra args
# (env assignments) are passed to `env`. Sets COMMIT_RC / COMMIT_OUT.
attempt_commit() {
    local dir="$1" query="$2"; shift 2
    printf 'x\n' >> "${dir}/work.txt"
    git -C "${dir}" add -A
    COMMIT_RC=0
    COMMIT_OUT="$(cd "${dir}" && env "$@" TDS_BRANCHGUARD_QUERY="${query}" \
        git commit -m change 2>&1)" || COMMIT_RC=$?
}

# Run the checker directly. query="" => unset it and strip PATH so gh is absent.
run_checker() {
    local repo="$1" branch="$2" query="$3"
    CHK_RC=0
    if [ -n "${query}" ]; then
        CHK_OUT="$(cd "${repo}" && TDS_BRANCHGUARD_QUERY="${query}" \
            "${CHECKER}" "${branch}" 2>&1)" || CHK_RC=$?
    else
        # Reliably simulate "gh absent": invoke the checker via an explicit bash
        # path (bypassing the shebang's PATH lookup) with PATH pointing at a
        # nonexistent dir, so `command -v gh` fails regardless of where gh lives.
        local bash_bin; bash_bin="$(command -v bash)"
        CHK_OUT="$(cd "${repo}" && unset TDS_BRANCHGUARD_QUERY && \
            PATH="${WORKROOT}/no-such-bin" "${bash_bin}" "${CHECKER}" "${branch}" 2>&1)" || CHK_RC=$?
    fi
}

# --- Checker unit tests ---

test_checker_states() {
    bold "Test: checker maps query states to exit codes"; printf '\n'
    local repo; repo="$(new_git_repo chk-unit)"
    local q="${WORKROOT}/q"

    make_query "${q}" merged
    run_checker "${repo}" feature "${q}"
    assert "MERGED => exit 0"        "[ ${CHK_RC} -eq 0 ]"
    assert "MERGED message names state" "grep -q 'MERGED' <<< \"\${CHK_OUT}\""
    assert "MERGED message names PR #"  "grep -q '123' <<< \"\${CHK_OUT}\""

    make_query "${q}" closed
    run_checker "${repo}" feature "${q}"
    assert "CLOSED => exit 0"        "[ ${CHK_RC} -eq 0 ]"
    assert "CLOSED message names state" "grep -q 'CLOSED' <<< \"\${CHK_OUT}\""

    make_query "${q}" open
    run_checker "${repo}" feature "${q}"
    assert "OPEN-only => exit 1 (alive)" "[ ${CHK_RC} -eq 1 ]"

    make_query "${q}" empty
    run_checker "${repo}" feature "${q}"
    assert "no PRs => exit 1 (alive)" "[ ${CHK_RC} -eq 1 ]"

    make_query "${q}" fail
    run_checker "${repo}" feature "${q}"
    assert "query non-zero => exit 2 (undetermined)" "[ ${CHK_RC} -eq 2 ]"
}

test_checker_no_gh() {
    bold "Test: no query seam and gh absent => exit 2 (fail-open)"; printf '\n'
    local repo; repo="$(new_git_repo chk-nogh)"
    run_checker "${repo}" feature ""
    assert "unset seam + gh missing => exit 2" "[ ${CHK_RC} -eq 2 ]"
}

# --- pre-commit hook tests ---

test_precommit_blocks_merged() {
    bold "Test: pre-commit BLOCKS a commit on a MERGED branch"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-merged)"
    git -C "${dir}" checkout -q -b feature
    local q="${WORKROOT}/pc-merged-q"; make_query "${q}" merged
    local before; before="$(head_of "${dir}")"
    attempt_commit "${dir}" "${q}"
    assert "commit fails"          "[ ${COMMIT_RC} -ne 0 ]"
    assert "HEAD unchanged"        "[ \"\$(head_of '${dir}')\" = '${before}' ]"
    assert "message shown"         "grep -q 'MERGED' <<< \"\${COMMIT_OUT}\""
}

test_precommit_allows_open() {
    bold "Test: pre-commit ALLOWS a commit on an OPEN branch"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-open)"
    git -C "${dir}" checkout -q -b feature
    local q="${WORKROOT}/pc-open-q"; make_query "${q}" open
    attempt_commit "${dir}" "${q}"
    assert "commit succeeds" "[ ${COMMIT_RC} -eq 0 ]"
}

test_precommit_detached_head() {
    bold "Test: pre-commit skips a detached HEAD"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-detached)"
    git -C "${dir}" checkout -q --detach
    local q="${WORKROOT}/pc-det-q"; make_query "${q}" merged
    attempt_commit "${dir}" "${q}"
    assert "detached HEAD commit succeeds" "[ ${COMMIT_RC} -eq 0 ]"
}

test_precommit_trunk_skip() {
    bold "Test: pre-commit skips trunk (default branch) even if MERGED"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-trunk)"
    # Pin the branch to a listed trunk name so the test is deterministic
    # regardless of the runner's init.defaultBranch.
    git -C "${dir}" branch -m master
    local q="${WORKROOT}/pc-trunk-q"; make_query "${q}" merged
    attempt_commit "${dir}" "${q}"
    assert "trunk commit succeeds" "[ ${COMMIT_RC} -eq 0 ]"
}

# An in-progress merge/rebase/cherry-pick must skip the guard (contract step 1)
# so an auto-generated merge commit is never blocked. Runs the hook directly to
# isolate it from git's own merge-commit machinery.
test_precommit_op_in_progress() {
    bold "Test: pre-commit skips when a merge/rebase is in progress"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-inprogress)"
    git -C "${dir}" checkout -q -b feature
    local q="${WORKROOT}/pc-inprogress-q"; make_query "${q}" merged
    local gitdir; gitdir="$(git -C "${dir}" rev-parse --git-dir)"
    gitdir="${dir}/${gitdir#"${dir}/"}"

    run_hook_direct() {
        HOOK_RC=0
        HOOK_OUT="$(cd "${dir}" && TDS_BRANCHGUARD_QUERY="${q}" \
            bash "${dir}/.git/hooks/pre-commit" 2>&1)" || HOOK_RC=$?
    }

    : > "${gitdir}/MERGE_HEAD"
    run_hook_direct
    rm -f "${gitdir}/MERGE_HEAD"
    assert "MERGE_HEAD skips guard (exit 0)" "[ ${HOOK_RC} -eq 0 ]"

    mkdir -p "${gitdir}/rebase-merge"
    run_hook_direct
    rm -rf "${gitdir}/rebase-merge"
    assert "rebase-merge skips guard (exit 0)" "[ ${HOOK_RC} -eq 0 ]"

    # Sanity: with no op in progress, the same MERGED branch IS blocked.
    run_hook_direct
    assert "no op in progress => blocked (exit 1)" "[ ${HOOK_RC} -eq 1 ]"
}

test_precommit_env_optout() {
    bold "Test: TDS_BRANCH_GUARD=0 opts out despite MERGED"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-envopt)"
    git -C "${dir}" checkout -q -b feature
    local q="${WORKROOT}/pc-envopt-q"; make_query "${q}" merged
    attempt_commit "${dir}" "${q}" TDS_BRANCH_GUARD=0
    assert "env opt-out commit succeeds" "[ ${COMMIT_RC} -eq 0 ]"
}

test_precommit_config_optout() {
    bold "Test: branchguard.enabled=false opts out despite MERGED"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-cfgopt)"
    git -C "${dir}" config branchguard.enabled false
    git -C "${dir}" checkout -q -b feature
    local q="${WORKROOT}/pc-cfgopt-q"; make_query "${q}" merged
    attempt_commit "${dir}" "${q}"
    assert "config opt-out commit succeeds" "[ ${COMMIT_RC} -eq 0 ]"
}

test_precommit_slash_branch_encoded() {
    bold "Test: slash branch blocks and writes percent-encoded .dead cache"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-slash)"
    git -C "${dir}" checkout -q -b feature/foo
    local q="${WORKROOT}/pc-slash-q"; make_query "${q}" merged
    attempt_commit "${dir}" "${q}"
    assert "slash-branch commit fails" "[ ${COMMIT_RC} -ne 0 ]"
    assert "dead cache key percent-encoded" \
        "[ -f '${dir}/.git/tds-branchguard/feature%2Ffoo.dead' ]"
}

test_precommit_percent_literal_no_collision() {
    bold "Test: a literal '%2F' in a branch name does not collide with '/'"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-pct)"
    # A branch literally named 'a%2Fb' must encode to 'a%252Fb' (percent first),
    # never colliding with branch 'a/b' which encodes to 'a%2Fb'.
    git -C "${dir}" checkout -q -b 'a%2Fb'
    local q="${WORKROOT}/pc-pct-q"; make_query "${q}" merged
    attempt_commit "${dir}" "${q}"
    assert "literal-%2F commit fails" "[ ${COMMIT_RC} -ne 0 ]"
    assert "cache key encodes '%' first" \
        "[ -f '${dir}/.git/tds-branchguard/a%252Fb.dead' ]"
    assert "no collision with the '/' encoding" \
        "[ ! -f '${dir}/.git/tds-branchguard/a%2Fb.dead' ]"
}

test_precommit_dead_cache_shortcircuits() {
    bold "Test: .dead marker blocks next commit with no network"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-cache)"
    git -C "${dir}" checkout -q -b feature
    local qm="${WORKROOT}/pc-cache-merged"; make_query "${qm}" merged
    attempt_commit "${dir}" "${qm}"
    assert "first commit blocked" "[ ${COMMIT_RC} -ne 0 ]"
    # Swap in an undetermined query; the dead marker must still block.
    local qf="${WORKROOT}/pc-cache-fail"; make_query "${qf}" fail
    local before; before="$(head_of "${dir}")"
    attempt_commit "${dir}" "${qf}"
    assert "cached commit still blocked" "[ ${COMMIT_RC} -ne 0 ]"
    assert "HEAD still unchanged" "[ \"\$(head_of '${dir}')\" = '${before}' ]"
}

test_precommit_fail_open() {
    bold "Test: undetermined query fails open and writes no .alive marker"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-failopen)"
    git -C "${dir}" checkout -q -b alivetest
    local q="${WORKROOT}/pc-failopen-q"; make_query "${q}" fail
    attempt_commit "${dir}" "${q}"
    assert "fail-open commit succeeds"  "[ ${COMMIT_RC} -eq 0 ]"
    assert "no .alive marker written" \
        "[ ! -f '${dir}/.git/tds-branchguard/alivetest.alive' ]"
}

test_precommit_unexpected_rc() {
    bold "Test: unexpected checker rc fails open WITHOUT caching alive"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-unexprc)"
    git -C "${dir}" checkout -q -b weirdrc
    # Stub checker that returns an out-of-contract code (3). The hook must allow
    # the commit but NOT write a stale .alive marker.
    local stub="${WORKROOT}/stub-checker-3"
    printf '#!/usr/bin/env bash\nexit 3\n' > "${stub}"; chmod +x "${stub}"
    git -C "${dir}" config branchguard.checkerPath "${stub}"
    attempt_commit "${dir}" "${WORKROOT}/unused-q"
    assert "unexpected-rc commit succeeds" "[ ${COMMIT_RC} -eq 0 ]"
    assert "no .alive marker cached" \
        "[ ! -f '${dir}/.git/tds-branchguard/weirdrc.alive' ]"
}

test_precommit_bypass() {
    bold "Test: --no-verify bypasses the guard on a MERGED branch"; printf '\n'
    local dir; dir="$(new_guarded_repo pc-bypass)"
    git -C "${dir}" checkout -q -b feature
    local q="${WORKROOT}/pc-bypass-q"; make_query "${q}" merged
    printf 'x\n' >> "${dir}/work.txt"
    git -C "${dir}" add -A
    local rc=0
    (cd "${dir}" && TDS_BRANCHGUARD_QUERY="${q}" \
        git commit --no-verify -m bypass >/dev/null 2>&1) || rc=$?
    assert "--no-verify commit succeeds" "[ ${rc} -eq 0 ]"
}

# --- Main ---

main() {
    bold "=== branch-guard smoke test ==="; printf '\n\n'
    assert "branch-merged-check is executable" "[ -x '${CHECKER}' ]"
    assert "pre-commit is executable"          "[ -x '${PRE_COMMIT}' ]"

    setup
    test_checker_states
    test_checker_no_gh
    test_precommit_blocks_merged
    test_precommit_allows_open
    test_precommit_detached_head
    test_precommit_trunk_skip
    test_precommit_op_in_progress
    test_precommit_env_optout
    test_precommit_config_optout
    test_precommit_slash_branch_encoded
    test_precommit_percent_literal_no_collision
    test_precommit_dead_cache_shortcircuits
    test_precommit_fail_open
    test_precommit_unexpected_rc
    test_precommit_bypass

    printf '\n'
    bold "=== Results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    [ "${TESTS_FAILED}" -gt 0 ] && red ", ${TESTS_FAILED} failed"
    printf ' ===\n'
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
