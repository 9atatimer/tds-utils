#!/usr/bin/env bash
# smoketest_bleed_guard.sh -- behavioral smoke test for bin/bleed-guard and its
# call from git-hooks/template/hooks/pre-commit (issue #366).
#
# Hermetic: no network, no sleeps. Each case builds a throwaway git repo, copies
# the REAL pre-commit hook into its .git/hooks, points bleedguard.checkerPath at
# the REAL checker and TDS_BLEED_DENYLIST at a fixture denylist. The branch
# guard is switched off (TDS_BRANCH_GUARD=0) so only the bleed guard decides.
#
# Usage: ./test/smoketest_bleed_guard.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
CHECKER="${REPO_DIR}/bin/bleed-guard"
PRE_COMMIT="${REPO_DIR}/git-hooks/template/hooks/pre-commit"

# The fixture secret. Deliberately not a real identifier.
SECRET="acct-0f0f0f-not-real"

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }

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

cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixtures ---

# write_denylist <path> -- comments, a blank line, a padded entry and the
# secret. A blank line that matched everything would block every commit.
write_denylist() {
    cat > "$1" <<EOF
# private identifiers -- never in a public repo

   ${SECRET}
another-private-thing
EOF
}

# make_repo <name> <marked:yes|no> -- a fresh repo on branch feature, with
# one clean commit, the real pre-commit hook and the real checker wired in.
make_repo() {
    local name="$1" marked="$2" repo
    repo="${WORKROOT}/${name}"
    git init -q -b main "${repo}"
    git -C "${repo}" config user.email t@example.invalid
    git -C "${repo}" config user.name t
    git -C "${repo}" config commit.gpgsign false
    git -C "${repo}" config bleedguard.checkerPath "${CHECKER}"
    rm -rf "${repo}/.git/hooks"
    mkdir -p "${repo}/.git/hooks"
    cp "${PRE_COMMIT}" "${repo}/.git/hooks/pre-commit"
    chmod +x "${repo}/.git/hooks/pre-commit"
    printf 'clean\n' > "${repo}/README"
    [ "${marked}" = yes ] && printf 'public\n' > "${repo}/PUBLIC.REPO"
    git -C "${repo}" add -A
    git -C "${repo}" commit -q --no-verify -m init
    git -C "${repo}" checkout -q -b feature
    printf '%s\n' "${repo}"
}

# try_commit <repo> <msg> -- run a real commit through the hooks. Sets RC and
# OUT (combined output). Never aborts the suite.
try_commit() {
    local repo="$1" msg="$2"
    set +e
    OUT="$(cd "${repo}" && TDS_BRANCH_GUARD=0 TDS_BLEED_DENYLIST="${DENYLIST}" \
        git commit -q -m "${msg}" 2>&1)"
    RC=$?
    set -e
}

contains() { case "$1" in *"$2"*) return 0 ;; esac; return 1; }

# --- Cases ---

case_blocks_added_line() {
    local repo
    repo="$(make_repo blocks yes)"
    printf 'endpoint = https://%s.example\n' "${SECRET}" > "${repo}/config"
    git -C "${repo}" add config
    try_commit "${repo}" leak
    assert "Given a public repo, When a staged line carries a denylisted string, Then the commit is refused" \
        '[ "${RC}" -ne 0 ]'
    assert "  ... and the refusal names the file and line" \
        'contains "${OUT}" "config:1"'
    assert "  ... and the refusal never echoes the denylisted string" \
        '! contains "${OUT}" "${SECRET}"'
}

case_allows_clean_commit() {
    local repo
    repo="$(make_repo clean yes)"
    printf 'nothing private here\n' > "${repo}/config"
    git -C "${repo}" add config
    try_commit "${repo}" clean
    assert "Given a public repo, When no staged line is denylisted, Then the commit lands (blank/comment lines in the list match nothing)" \
        '[ "${RC}" -eq 0 ]'
}

case_matches_case_insensitively() {
    local repo upper
    repo="$(make_repo nocase yes)"
    upper="$(printf '%s' "${SECRET}" | tr '[:lower:]' '[:upper:]')"
    printf '%s\n' "${upper}" > "${repo}/config"
    git -C "${repo}" add config
    try_commit "${repo}" upper
    assert "Given a public repo, When the string is staged in another case, Then the commit is refused" \
        '[ "${RC}" -ne 0 ]'
}

case_blocks_added_path() {
    local repo
    repo="$(make_repo path yes)"
    printf 'x\n' > "${repo}/${SECRET}.txt"
    git -C "${repo}" add -A
    try_commit "${repo}" path
    assert "Given a public repo, When a staged file NAME carries the string, Then the commit is refused" \
        '[ "${RC}" -ne 0 ]'
}

case_allows_removing_a_leak() {
    local repo
    repo="$(make_repo removal yes)"
    printf '%s\n' "${SECRET}" > "${repo}/old"
    git -C "${repo}" add old
    git -C "${repo}" commit -q --no-verify -m "pre-existing leak"
    git -C "${repo}" rm -q old
    try_commit "${repo}" scrub
    assert "Given a leak already committed, When the commit only removes it, Then the commit lands" \
        '[ "${RC}" -eq 0 ]'
}

case_guards_trunk() {
    local repo
    repo="$(make_repo trunk yes)"
    git -C "${repo}" checkout -q main
    printf '%s\n' "${SECRET}" > "${repo}/config"
    git -C "${repo}" add config
    try_commit "${repo}" trunk
    assert "Given a public repo on its default branch, When a denylisted line is staged, Then the commit is still refused" \
        '[ "${RC}" -ne 0 ]'
}

case_survives_non_utf8() {
    local repo
    repo="$(make_repo latin1 yes)"
    # A Latin-1 byte (0xE9) ahead of the leak: under a UTF-8 locale BSD awk
    # dies on it, and a matcher that dies reports nothing -- a silent pass.
    printf 'caf\351\n%s\n' "${SECRET}" > "${repo}/config"
    git -C "${repo}" add config
    try_commit "${repo}" latin1
    assert "Given a staged file with a non-UTF-8 byte, When a later line is denylisted, Then the commit is still refused" \
        '[ "${RC}" -ne 0 ] && contains "${OUT}" "config:2"'
}

case_redacts_file_name() {
    local repo
    repo="$(make_repo redact yes)"
    printf 'x\n' > "${repo}/${SECRET}.txt"
    git -C "${repo}" add -A
    try_commit "${repo}" redact
    assert "Given a denylisted file NAME, When the commit is refused, Then the refusal never echoes the string" \
        '[ "${RC}" -ne 0 ] && ! contains "${OUT}" "${SECRET}"'
}

case_scans_lines_that_look_like_headers() {
    local repo
    repo="$(make_repo plusplus yes)"
    # An added line "++ x" shows in the patch as "+++ x", the shape of a
    # file header; it is content and must be scanned.
    printf '++ %s\n' "${SECRET}" > "${repo}/config"
    git -C "${repo}" add config
    try_commit "${repo}" plusplus
    assert "Given a staged line starting with '++ ', When it is denylisted, Then the commit is refused" \
        '[ "${RC}" -ne 0 ]'
}

case_marker_read_from_index() {
    local repo
    repo="$(make_repo unstagedmarker yes)"
    rm "${repo}/PUBLIC.REPO"
    printf '%s\n' "${SECRET}" > "${repo}/config"
    git -C "${repo}" add config
    try_commit "${repo}" marker
    assert "Given PUBLIC.REPO deleted only in the work tree, When a denylisted line is staged, Then the commit is still refused" \
        '[ "${RC}" -ne 0 ]'
}

case_guards_merge_resolution() {
    local repo
    repo="$(make_repo merge yes)"
    printf 'theirs\n' > "${repo}/README"
    git -C "${repo}" commit -q --no-verify -am theirs
    git -C "${repo}" checkout -q main
    printf 'ours\n' > "${repo}/README"
    git -C "${repo}" commit -q --no-verify -am ours
    git -C "${repo}" merge -q feature >/dev/null 2>&1 || true
    printf 'resolved %s\n' "${SECRET}" > "${repo}/README"
    git -C "${repo}" add README
    try_commit "${repo}" merge
    assert "Given a conflicted merge, When the resolution stages a denylisted line, Then the merge commit is refused" \
        '[ "${RC}" -ne 0 ]'
}

case_ignores_private_repo() {
    local repo
    repo="$(make_repo private no)"
    printf '%s\n' "${SECRET}" > "${repo}/config"
    git -C "${repo}" add config
    try_commit "${repo}" private
    assert "Given a repo with no PUBLIC.REPO marker, When a denylisted line is staged, Then the commit lands" \
        '[ "${RC}" -eq 0 ]'
}

case_skips_without_denylist() {
    local repo saved="${DENYLIST}"
    repo="$(make_repo nolist yes)"
    printf '%s\n' "${SECRET}" > "${repo}/config"
    git -C "${repo}" add config
    DENYLIST="${WORKROOT}/does-not-exist"
    try_commit "${repo}" nolist
    DENYLIST="${saved}"
    assert "Given a machine with no denylist, When a public repo commits, Then the commit lands" \
        '[ "${RC}" -eq 0 ]'
    assert "  ... and the skip is announced, not silent" \
        'contains "${OUT}" "bleed-guard"'
}

case_opt_out() {
    local repo
    repo="$(make_repo optout yes)"
    printf '%s\n' "${SECRET}" > "${repo}/config"
    git -C "${repo}" add config
    set +e
    OUT="$(cd "${repo}" && TDS_BRANCH_GUARD=0 TDS_BLEED_GUARD=0 \
        TDS_BLEED_DENYLIST="${DENYLIST}" git commit -q -m optout 2>&1)"
    RC=$?
    set -e
    assert "Given TDS_BLEED_GUARD=0, When a denylisted line is staged, Then the commit lands" \
        '[ "${RC}" -eq 0 ]'
}

case_tree_audit() {
    local repo
    repo="$(make_repo tree yes)"
    printf 'a\nb %s\n' "${SECRET}" > "${repo}/legacy"
    git -C "${repo}" add legacy
    git -C "${repo}" commit -q --no-verify -m legacy
    set +e
    OUT="$(cd "${repo}" && TDS_BLEED_DENYLIST="${DENYLIST}" "${CHECKER}" --tree 2>&1)"
    RC=$?
    set -e
    assert "Given a leak already committed, When bleed-guard --tree audits the repo, Then it exits non-zero" \
        '[ "${RC}" -ne 0 ]'
    assert "  ... and names the file and line" \
        'contains "${OUT}" "legacy:2"'
}

# --- Main ---

main() {
    WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/bleed-guard-test.XXXXXX")"
    DENYLIST="${WORKROOT}/denylist"
    write_denylist "${DENYLIST}"

    case_blocks_added_line
    case_allows_clean_commit
    case_matches_case_insensitively
    case_blocks_added_path
    case_allows_removing_a_leak
    case_guards_trunk
    case_survives_non_utf8
    case_redacts_file_name
    case_scans_lines_that_look_like_headers
    case_marker_read_from_index
    case_guards_merge_resolution
    case_ignores_private_repo
    case_skips_without_denylist
    case_opt_out
    case_tree_audit

    printf '\n%d run, %d passed, %d failed\n' "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
