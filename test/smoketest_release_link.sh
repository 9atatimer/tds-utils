#!/usr/bin/env bash
# smoketest_release_link.sh -- behavioral smoke test for bin/tds-release-link.
#
# Hermetic: no network, no sleeps, and never touches the real $HOME. Each case
# builds a throwaway repo with a `release` worktree plus a fake home full of
# symlinks into the primary checkout, then drives the linker at it via
# TDS_RELEASE_REPO / TDS_RELEASE_HOME.
#
# Usage: ./test/smoketest_release_link.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
LINKER="${REPO_DIR}/bin/tds-release-link"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1"
    local condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

cleanup() { [ -n "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixture ---------------------------------------------------------------

REPO=""
RELEASE=""
HOME_DIR=""

# make_fixture <name> -- repo + release worktree + fake home with three links
# into the primary checkout, one already-released link, and one real file.
make_fixture() {
    local name="$1"
    REPO="${WORKROOT}/${name}"
    RELEASE="${WORKROOT}/${name}-release"
    HOME_DIR="${WORKROOT}/${name}-home"

    mkdir -p "${REPO}/macos" "${REPO}/clai.d/claude" "${REPO}/emacs/dot.emacs.d"
    git -C "${REPO}" init -q -b master
    git -C "${REPO}" config user.email t@example.com
    git -C "${REPO}" config user.name  Test
    echo zshrc      > "${REPO}/macos/dot.zshrc"
    echo statusline > "${REPO}/clai.d/claude/statusline.sh"
    echo init       > "${REPO}/emacs/dot.emacs.d/init.el"
    git -C "${REPO}" add -A
    git -C "${REPO}" commit -qm one
    git -C "${REPO}" branch release
    git -C "${REPO}" worktree add -q "${RELEASE}" release

    mkdir -p "${HOME_DIR}/.claude"
    ln -s "${REPO}/macos/dot.zshrc"              "${HOME_DIR}/.zshrc"
    ln -s "${REPO}/emacs/dot.emacs.d"            "${HOME_DIR}/.emacs.d"
    ln -s "${REPO}/clai.d/claude/statusline.sh"  "${HOME_DIR}/.claude/statusline.sh"
    ln -s "${RELEASE}/clai.d"                       "${HOME_DIR}/clai.d"
    echo "not a link" > "${HOME_DIR}/.realfile"
}

run_link() {
    TDS_RELEASE_REPO="${REPO}" TDS_RELEASE_HOME="${HOME_DIR}" \
        "${LINKER}" "$@" >"${WORKROOT}/out" 2>&1
}

target_of() { readlink "$1"; }
# git canonicalises worktree paths (/var -> /private/var on macOS), so the
# links it writes are canonical. Compare like against like.
canon()     { ( cd "$1" >/dev/null 2>&1 && pwd -P ); }

# --- Cases -----------------------------------------------------------------

case_repoints() {
    bold "case: repoints checkout links at the release worktree"; echo
    make_fixture repoint
    run_link && rc=0 || rc=$?
    assert "exits 0"                    "[ ${rc} -eq 0 ]"
    assert ".zshrc now via release"        "[ \"$(target_of "${HOME_DIR}/.zshrc")\" = \"$(canon "${RELEASE}")/macos/dot.zshrc\" ]"
    assert ".emacs.d now via release"      "[ \"$(target_of "${HOME_DIR}/.emacs.d")\" = \"$(canon "${RELEASE}")/emacs/dot.emacs.d\" ]"
    assert "nested link now via release"   "[ \"$(target_of "${HOME_DIR}/.claude/statusline.sh")\" = \"$(canon "${RELEASE}")/clai.d/claude/statusline.sh\" ]"
    assert "links still resolve"        "[ -f \"${HOME_DIR}/.zshrc\" ] && [ -f \"${HOME_DIR}/.claude/statusline.sh\" ]"
    assert "content unchanged"          "[ \"\$(cat "${HOME_DIR}/.zshrc")\" = zshrc ]"
    assert "real file untouched"        "[ ! -L \"${HOME_DIR}/.realfile\" ]"
}

case_idempotent() {
    bold "case: idempotent"; echo
    make_fixture idem
    run_link
    local first
    first="$(target_of "${HOME_DIR}/.zshrc")"
    run_link && rc=0 || rc=$?
    assert "second run exits 0"         "[ ${rc} -eq 0 ]"
    assert "target unchanged"           "[ \"$(target_of "${HOME_DIR}/.zshrc")\" = \"${first}\" ]"
    assert "reports nothing to do"      "grep -qiE 'already|no links' '${WORKROOT}/out'"
}

case_dry_run() {
    bold "case: dry run changes nothing"; echo
    make_fixture dry
    local before
    before="$(target_of "${HOME_DIR}/.zshrc")"
    run_link -n && rc=0 || rc=$?
    assert "exits 0"                    "[ ${rc} -eq 0 ]"
    assert "link unchanged"             "[ \"$(target_of "${HOME_DIR}/.zshrc")\" = \"${before}\" ]"
    assert "names the link"             "grep -q '.zshrc' '${WORKROOT}/out'"
}

case_revert() {
    bold "case: revert points back at the primary checkout"; echo
    make_fixture rev
    run_link
    run_link -r && rc=0 || rc=$?
    assert "exits 0"                    "[ ${rc} -eq 0 ]"
    assert ".zshrc back on checkout"    "[ \"$(target_of "${HOME_DIR}/.zshrc")\" = \"${REPO}/macos/dot.zshrc\" ]"
    assert "nested link back too"       "[ \"$(target_of "${HOME_DIR}/.claude/statusline.sh")\" = \"${REPO}/clai.d/claude/statusline.sh\" ]"
    assert "still resolves"             "[ -f \"${HOME_DIR}/.zshrc\" ]"
}

case_no_release_worktree() {
    bold "case: missing release worktree refused"; echo
    make_fixture nolive
    git -C "${REPO}" worktree remove --force "${RELEASE}"
    local before
    before="$(target_of "${HOME_DIR}/.zshrc")"
    run_link && rc=0 || rc=$?
    assert "exits non-zero"             "[ ${rc} -ne 0 ]"
    assert "link unchanged"             "[ \"$(target_of "${HOME_DIR}/.zshrc")\" = \"${before}\" ]"
    assert "names the release branch"      "grep -qi 'release' '${WORKROOT}/out'"
}

case_dangling_refused() {
    bold "case: a link whose release counterpart is missing is left alone"; echo
    make_fixture dangle
    ln -s "${REPO}/macos/dot.nonexistent" "${HOME_DIR}/.ghost"
    run_link && rc=0 || rc=$?
    assert "exits 0"                    "[ ${rc} -eq 0 ]"
    assert "ghost link untouched"       "[ \"$(target_of "${HOME_DIR}/.ghost")\" = \"${REPO}/macos/dot.nonexistent\" ]"
    assert "real links still moved"     "[ \"$(target_of "${HOME_DIR}/.zshrc")\" = \"$(canon "${RELEASE}")/macos/dot.zshrc\" ]"
    assert "warns about the skip"       "grep -qiE 'skip|missing' '${WORKROOT}/out'"
}

main() {
    [ -x "${LINKER}" ] || { red "FAIL"; printf ' missing or non-executable: %s\n' "${LINKER}"; exit 1; }
    WORKROOT="$(mktemp -d)"
    case_repoints
    case_idempotent
    case_dry_run
    case_revert
    case_no_release_worktree
    case_dangling_refused
    echo
    printf 'ran %d, passed %d, failed %d\n' "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
