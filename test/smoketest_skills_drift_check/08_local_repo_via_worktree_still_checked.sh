#!/usr/bin/env bash
# Regression test for the Copilot review finding on PR #265: a git
# WORKTREE (this fleet's own CLAUDE.md convention puts these under
# ~/workplace/.worktrees/) has a `.git` FILE (a `gitdir:` pointer), not a
# `.git` directory. Given SKILLS_REPO_PATH points at a worktree, not the
# primary clone, When skills-drift-check runs, Then the local source is
# still evaluated (not silently skipped) -- proving the fix from a bare
# `[ -d "$repo/.git" ]` check to `git rev-parse --is-inside-work-tree`.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d "${TMPDIR:-/tmp}/skills-drift-check-smoke.XXXXXX")}"
    require_check_bin || return 1
    local dir rc primary worktree
    dir="$(scenario_dir via_worktree)"
    primary="${dir}/skills-repo-primary"
    worktree="${dir}/skills-repo-worktree"
    make_skills_repo "${primary}" 4
    git -C "${primary}" worktree add -q "${worktree}" -b wt-branch >/dev/null 2>&1

    # A `.git` FILE, not a directory -- the exact shape the old check missed.
    [[ -f "${worktree}/.git" ]] || { echo "FAIL: test setup did not produce a gitfile worktree"; return 1; }

    make_lmde_stub "${dir}/bin/lmde" "0.2.999"
    seed_stamp "${dir}/home" "0.2.999"

    rc="$(run_check "${dir}" --repo "${worktree}")"

    assert_eq "${rc}" "1" "the worktree's local version (0.2.5) must be evaluated, not skipped" || return 1
    assert_stdout_contains "${dir}" "local repo HEAD (0.2.5) != published 0.2.999" \
        "local source detected through a .git FILE, not just a .git directory" || return 1
}
main "$@"
