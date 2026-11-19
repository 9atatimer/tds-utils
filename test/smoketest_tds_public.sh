#!/usr/bin/env bash
# smoketest_tds_public.sh -- behavioral smoke test for bin/tds-public
# (docs/design/DESIGN.PUBLIC-RELEASE.md, Behaviors and Interfaces).
#
# Hermetic: no network, no sleeps, no real remote. Each case builds a scratch
# source repo with a `release` branch, a fixture denylist and a local bare repo
# as the target remote, then drives the tool at them with TDS_PUBLIC_SOURCE,
# TDS_PUBLIC_REMOTE and TDS_BLEED_DENYLIST. The tool runs under `env -i` with a
# temp HOME, so the real denylist and the real git config are never read.
#
# Usage: /bin/bash test/smoketest_tds_public.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
TOOL="${REPO_DIR}/bin/tds-public"

# The fixture secret. Deliberately not a real identifier.
SECRET="ZZPRIVATEFIXTURE"

# Fixture git identity and isolation for every git the test itself runs.
export GIT_AUTHOR_NAME="Fixture" GIT_AUTHOR_EMAIL="fixture@example.invalid"
export GIT_COMMITTER_NAME="Fixture" GIT_COMMITTER_EMAIL="fixture@example.invalid"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

# Per-case state, set by make_case and run_tool.
INITIAL_HEAD="" SRC="" REMOTE="" CWD="" HOME_DIR="" GITCONFIG="" DENYLIST_PATH="" SHA=""
RC=0 OUT="" REMOTE_BEFORE="" REMOTE_AFTER=""

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

cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; return 0; }
trap cleanup EXIT INT TERM HUP

# --- Predicates and probes ---

contains()    { case "$1" in *"$2"*) return 0 ;; esac; return 1; }
# contains_ci <text> <ERE> -- case-insensitive extended-regex match.
contains_ci() { printf '%s\n' "$1" | grep -qiE -- "$2"; }

# Every ref of the target remote: a push of anything changes this.
remote_state() { git -C "${REMOTE}" for-each-ref 2>/dev/null || true; }
remote_head()  { git -C "${REMOTE}" rev-parse HEAD; }
remote_count() { git -C "${REMOTE}" rev-list --count HEAD; }
remote_paths() { git -C "${REMOTE}" ls-tree -r --name-only HEAD | sort | tr '\n' ' '; }
remote_oid()   { git -C "${REMOTE}" rev-parse "HEAD:$1" 2>/dev/null || echo missing; }
remote_mode()  { git -C "${REMOTE}" ls-tree HEAD -- "$1" | cut -d' ' -f1; }
remote_msg()   { git -C "${REMOTE}" log -1 --format=%B HEAD; }
remote_has()   { git -C "${REMOTE}" cat-file -e "HEAD:$1" 2>/dev/null; }
src_oid()      { git -C "${SRC}" rev-parse "${SHA}:$1"; }

# --- Fixtures ---

# make_case <name> -- a scratch source repo (branch main), a bare target remote
# whose default branch already holds one commit (file OLD-TARGET-FILE), a
# fixture denylist and an isolated HOME. Sets the per-case globals.
make_case() {
    local name="$1" seed
    CWD="${WORKROOT}/${name}/cwd"
    SRC="${WORKROOT}/${name}/src"
    REMOTE="${WORKROOT}/${name}/target.git"
    HOME_DIR="${WORKROOT}/${name}/home"
    GITCONFIG="${WORKROOT}/${name}/gitconfig"
    DENYLIST_PATH="${WORKROOT}/${name}/denylist"
    seed="${WORKROOT}/${name}/seed"
    mkdir -p "${CWD}" "${HOME_DIR}"
    : > "${GITCONFIG}"
    git init -q -b main "${SRC}"
    git init -q --bare -b main "${REMOTE}"
    git init -q -b main "${seed}"
    printf 'previous snapshot\n' > "${seed}/OLD-TARGET-FILE"
    git -C "${seed}" add -A
    git -C "${seed}" commit -q -m 'initial'
    git -C "${seed}" push -q "${REMOTE}" main
    INITIAL_HEAD="$(git -C "${REMOTE}" rev-parse HEAD)"
    cat > "${DENYLIST_PATH}" <<LIST
# private identifiers -- never published

   ${SECRET}
LIST
}

# src_file <path> <content> -- write a file into the source work tree.
src_file() {
    mkdir -p "$(dirname "${SRC}/$1")"
    printf '%s' "$2" > "${SRC}/$1"
}

# src_allow <target> <line>... -- write publish/<target>.allow.
src_allow() {
    local target="$1"; shift
    mkdir -p "${SRC}/publish"
    printf '%s\n' "$@" > "${SRC}/publish/${target}.allow"
}

# release_now -- commit everything and move `release` to it. Sets SHA.
release_now() {
    git -C "${SRC}" add -A
    git -C "${SRC}" commit -q --allow-empty -m "source change"
    git -C "${SRC}" branch -f release HEAD
    SHA="$(git -C "${SRC}" rev-parse HEAD)"
}

# run_tool <args...> -- run the tool hermetically. Sets RC, OUT (stdout and
# stderr combined) and the remote's ref state before and after. Never aborts
# the suite. DENYLIST_PATH empty means TDS_BLEED_DENYLIST is unset.
run_tool() {
    local -a envargs
    envargs=(PATH="${PATH}" HOME="${HOME_DIR}" LC_ALL=C
        GIT_CONFIG_GLOBAL="${GITCONFIG}" GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
        GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME}" GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL}"
        GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME}" GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL}"
        TDS_PUBLIC_SOURCE="${SRC}" TDS_PUBLIC_REMOTE="${REMOTE}")
    [ -z "${DENYLIST_PATH}" ] || envargs+=(TDS_BLEED_DENYLIST="${DENYLIST_PATH}")
    REMOTE_BEFORE="$(remote_state)"
    set +e
    OUT="$(cd "${CWD}" && env -i "${envargs[@]}" "${TOOL}" "$@" 2>&1)"
    RC=$?
    set -e
    REMOTE_AFTER="$(remote_state)"
}

# assert_refused -- the shared shape of every refusal: exit 1, target untouched,
# and the matched denylist text never printed.
assert_refused() {
    assert "  ... and the exit is 1" '[ "${RC}" -eq 1 ]'
    assert "  ... and nothing is pushed (the target's refs are unchanged)" \
        '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
    assert "  ... and the output never carries the denylisted text" \
        '! contains_ci "${OUT}" "${SECRET}"'
}

# workflow_case <name> <yaml> <ok|refuse> -- publish `workflows` with one
# selected workflow file whose content is <yaml>.
workflow_case() {
    local name="$1" yaml="$2" want="$3"
    make_case "${name}"
    src_file .github/workflows/w.yml "${yaml}"
    src_allow workflows .github/workflows/w.yml
    release_now
    run_tool workflows "${SHA}"
    if [ "${want}" = refuse ]; then
        assert "Given a workflow ${name}, When workflows is published, Then it is refused" \
            '[ "${RC}" -eq 1 ]'
        assert "  ... and the output names the workflow" \
            'contains "${OUT}" ".github/workflows/w.yml"'
        assert "  ... and the output names the trigger rule" \
            'contains_ci "${OUT}" "workflow_call|trigger"'
        assert "  ... and nothing is pushed" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
    else
        assert "Given a workflow ${name}, When workflows is published, Then it is published" \
            '[ "${RC}" -eq 0 ] && remote_has .github/workflows/w.yml'
    fi
}

# --- Cases: one per row of Behaviors and Interfaces ---

case_publishes_allowlisted_tree() {
    bold "case: a release publishes its allow-listed tree"; echo
    make_case publish
    src_file bin/a $'#!/bin/sh\r\necho a\n\x01\x02 no trailing newline'
    chmod +x "${SRC}/bin/a"
    src_file lib/x/deep/f $'plain\n'
    src_file bin/plain $'no exec bit\n'
    src_file bin/b 'not listed'
    src_allow tds-utils-public '# the mirror' '' bin/a bin/plain 'lib/x/**'
    release_now
    run_tool tds-utils-public "${SHA}"
    assert "Given a released commit and an allow-list, When the target is published, Then the exit is 0" \
        '[ "${RC}" -eq 0 ]'
    assert "  ... and the target gained exactly one commit whose parent is the previous head" \
        '[ "$(remote_count)" -eq 2 ] && [ "$(git -C "${REMOTE}" rev-parse HEAD^)" = "${INITIAL_HEAD}" ]'
    assert "  ... and the commit message is exactly release <full sha>" \
        '[ "$(remote_msg)" = "release ${SHA}" ]'
    assert "  ... and the tree holds the selection and nothing else (the old target file is gone)" \
        '[ "$(remote_paths)" = "bin/a bin/plain lib/x/deep/f " ]'
    assert "  ... and a selected file is byte-identical to the released commit" \
        '[ "$(remote_oid bin/a)" = "$(src_oid bin/a)" ] && [ "$(remote_oid lib/x/deep/f)" = "$(src_oid lib/x/deep/f)" ]'
    assert "  ... and the executable bit survives, and a plain file stays plain" \
        '[ "$(remote_mode bin/a)" = 100755 ] && [ "$(remote_mode bin/plain)" = 100644 ]'
}

case_unlisted_file_never_published() {
    bold "case: an unlisted file is never published"; echo
    make_case unlisted
    src_file bin/a 'listed'
    src_file bin/b "unlisted, and it holds ${SECRET}"
    src_allow workflows bin/a
    release_now
    run_tool workflows "${SHA}"
    assert "Given bin/b that no line names, When published, Then the exit is 0" '[ "${RC}" -eq 0 ]'
    assert "  ... and the target has no bin/b" '! remote_has bin/b'
    assert "  ... and the target has bin/a" 'remote_has bin/a'
}

case_denylist_hit_refuses() {
    bold "case: a denylist hit refuses everything"; echo
    make_case hit
    src_file bin/a $'clean line\n'"endpoint ${SECRET} here"$'\n'
    src_file bin/ok 'fine'
    src_allow workflows bin/a bin/ok
    release_now
    run_tool workflows "${SHA}"
    assert "Given a selected file containing a denylist entry, When published, Then the output names file:line" \
        'contains "${OUT}" "bin/a:2"'
    assert_refused
}

case_denylist_via_git_config() {
    bold "case: the denylist resolves through git config"; echo
    make_case cfgdeny
    src_file bin/a "leak ${SECRET}"$'\n'
    src_allow workflows bin/a
    release_now
    printf '[bleedguard]\n\tdenylist = %s\n' "${DENYLIST_PATH}" > "${GITCONFIG}"
    DENYLIST_PATH=""
    run_tool workflows "${SHA}"
    assert "Given TDS_BLEED_DENYLIST unset and bleedguard.denylist configured, When a selected file hits it, Then it is refused" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "bin/a:1"'
    assert "  ... and nothing is pushed" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_no_denylist_refuses() {
    bold "case: no denylist refuses"; echo
    make_case nodeny
    src_file bin/a 'clean'
    src_allow workflows bin/a
    release_now
    DENYLIST_PATH=""
    run_tool workflows "${SHA}"
    assert "Given no denylist anywhere (env, git config, default under HOME), When published, Then the refusal says so" \
        'contains_ci "${OUT}" "denylist"'
    assert_refused
    DENYLIST_PATH="${WORKROOT}/nodeny/does-not-exist"
    run_tool workflows "${SHA}"
    assert "Given TDS_BLEED_DENYLIST naming a missing file, When published, Then it is refused too" \
        '[ "${RC}" -eq 1 ] && [ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_stale_allow_line_refuses() {
    bold "case: a stale allow-list line refuses"; echo
    make_case stale
    src_file bin/a 'x'
    src_allow workflows bin/a bin/renamed-away
    release_now
    run_tool workflows "${SHA}"
    assert "Given a line matching no file, When published, Then the line is named" \
        'contains "${OUT}" "bin/renamed-away"'
    assert "  ... and the refusal names the allow-list rule" 'contains_ci "${OUT}" "allow"'
    assert_refused
}

case_workflow_triggers() {
    bold "case: a workflow with its own trigger refuses (workflows target)"; echo
    workflow_case "with on: push" $'on: push\njobs: {}\n' refuse
    workflow_case "with on: [push, workflow_call]" $'on: [push, workflow_call]\njobs: {}\n' refuse
    workflow_case "with workflow_call and workflow_dispatch" \
        $'on:\n  workflow_call:\n  workflow_dispatch:\njobs: {}\n' refuse
    workflow_case "with workflow_call only, with inputs" \
        $'on:\n  workflow_call:\n    inputs:\n      tools_ref:\n        type: string\njobs: {}\n' ok
    workflow_case "with on: workflow_call as a scalar" $'on: workflow_call\njobs: {}\n' ok
}

case_trigger_rule_only_for_workflows_target() {
    bold "case: the trigger rule applies only to the workflows target"; echo
    make_case trigscope
    src_file docs/sample.yml $'on: push\njobs: {}\n'
    src_allow tds-utils-public docs/sample.yml
    release_now
    run_tool tds-utils-public "${SHA}"
    assert "Given a non-workflow YAML with on: push on the mirror, When published, Then it is published" \
        '[ "${RC}" -eq 0 ] && remote_has docs/sample.yml'
    make_case trigscope2
    src_file docs/sample.yml $'on: push\njobs: {}\n'
    src_allow workflows docs/sample.yml
    release_now
    run_tool workflows "${SHA}"
    assert "Given a YAML outside .github/workflows with on: push on workflows, When published, Then it is not treated as a workflow" \
        '[ "${RC}" -eq 0 ] && remote_has docs/sample.yml'
}

case_mirror_never_receives_github() {
    bold "case: the mirror never receives .github/"; echo
    make_case mirrorgh
    src_file .github/x 'anything'
    src_file bin/a 'fine'
    src_allow tds-utils-public bin/a .github/x
    release_now
    run_tool tds-utils-public "${SHA}"
    assert "Given a tds-utils-public allow-list selecting .github/x, When published, Then the path is named" \
        'contains "${OUT}" ".github/x"'
    assert_refused
    make_case workflowsgh
    src_file .github/x 'anything'
    src_allow workflows .github/x
    release_now
    run_tool workflows "${SHA}"
    assert "Given the same selection on workflows, When published, Then the .github/ rule does not apply" \
        '[ "${RC}" -eq 0 ] && remote_has .github/x'
}

case_git_crypt_file_refuses() {
    bold "case: a git-crypt file refuses"; echo
    make_case crypt
    printf 'secret.bin filter=git-crypt diff=git-crypt\n' > "${SRC}/.gitattributes"
    src_file secret.bin 'ciphertext stand-in'
    src_file bin/a 'fine'
    src_allow workflows bin/a secret.bin
    release_now
    run_tool workflows "${SHA}"
    assert "Given a selected file marked filter=git-crypt, When published, Then the file is named" \
        'contains "${OUT}" "secret.bin"'
    assert "  ... and the output names the encryption rule" 'contains_ci "${OUT}" "git-crypt|encrypt"'
    assert_refused
}

case_symlink_to_unselected_refuses() {
    bold "case: a symlink to an unselected path refuses"; echo
    make_case dangling
    src_file bin/b 'not selected'
    ln -s b "${SRC}/bin/link"
    src_allow workflows bin/link
    release_now
    run_tool workflows "${SHA}"
    assert "Given a selected symlink whose target is not selected, When published, Then the link is named" \
        'contains "${OUT}" "bin/link"'
    assert "  ... and the output names the symlink rule" 'contains_ci "${OUT}" "symlink|link"'
    assert_refused
}

case_symlink_to_selected_publishes() {
    bold "case: a symlink whose target is selected publishes"; echo
    make_case okLink
    src_file bin/b 'selected'
    ln -s b "${SRC}/bin/link"
    src_allow workflows bin/b bin/link
    release_now
    run_tool workflows "${SHA}"
    assert "Given a selected symlink and its selected target, When published, Then the exit is 0" \
        '[ "${RC}" -eq 0 ]'
    assert "  ... and the link is published as a symlink with the same target" \
        '[ "$(remote_mode bin/link)" = 120000 ] && [ "$(remote_oid bin/link)" = "$(src_oid bin/link)" ]'
}

case_unchanged_release_adds_no_commit() {
    bold "case: an unchanged release adds no commit"; echo
    make_case unchanged
    src_file bin/a 'same'
    src_allow workflows bin/a
    release_now
    run_tool workflows "${SHA}"
    local head1
    head1="$(remote_head)"
    run_tool workflows "${SHA}"
    assert "Given a target whose head already holds the snapshot, When published again, Then the exit is 0" \
        '[ "${RC}" -eq 0 ]'
    assert "  ... and no commit is made" \
        '[ "$(remote_head)" = "${head1}" ] && [ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
    # An unrelated source commit that leaves the selection alone is still unchanged.
    src_file bin/unrelated 'private change'
    release_now
    run_tool workflows "${SHA}"
    assert "Given a new release whose selection is byte-identical, When published, Then still no commit" \
        '[ "${RC}" -eq 0 ] && [ "$(remote_head)" = "${head1}" ]'
}

case_second_publish_chains_commits() {
    bold "case: a second publish after a change builds on the first"; echo
    make_case chain
    src_file bin/a 'v1'
    src_allow workflows bin/a
    release_now
    run_tool workflows "${SHA}"
    local first sha1
    first="$(remote_head)"; sha1="${SHA}"
    src_file bin/a 'v2'
    release_now
    run_tool workflows "${SHA}"
    assert "Given a published target and a changed selection, When published, Then the exit is 0" \
        '[ "${RC}" -eq 0 ]'
    assert "  ... and the new commit's parent is the first publication" \
        '[ "$(git -C "${REMOTE}" rev-parse HEAD^)" = "${first}" ] && [ "$(remote_count)" -eq 3 ]'
    assert "  ... and its message names the new released sha, not the old one" \
        '[ "$(remote_msg)" = "release ${SHA}" ] && [ "${SHA}" != "${sha1}" ]'
    assert "  ... and the content is the new one" '[ "$(remote_oid bin/a)" = "$(src_oid bin/a)" ]'
}

case_only_released_commit_published() {
    bold "case: only the released commit is published"; echo
    make_case unreleased
    src_file bin/a 'v1'
    src_allow workflows bin/a
    release_now
    local old="${SHA}"
    src_file bin/a 'v2'
    git -C "${SRC}" add -A
    git -C "${SRC}" commit -q -m 'not released yet'
    SHA="$(git -C "${SRC}" rev-parse HEAD)"
    run_tool workflows "${SHA}"
    assert "Given a sha that is not the head of release, When published, Then the output says so" \
        'contains_ci "${OUT}" "release"'
    assert_refused
    git -C "${SRC}" branch -f release main
    run_tool workflows "${old}"
    assert "Given release has moved on, When an older released sha is published, Then it is refused too" \
        '[ "${RC}" -eq 1 ] && [ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_dry_run_publishes_nothing() {
    bold "case: a dry run publishes nothing"; echo
    make_case dry
    src_file bin/a 'a'
    src_file lib/x/deep/f 'f'
    src_file bin/b 'unlisted'
    src_allow workflows bin/a 'lib/x/**'
    release_now
    run_tool -n workflows "${SHA}"
    assert "Given a clean release, When run with -n, Then the exit is 0" '[ "${RC}" -eq 0 ]'
    assert "  ... and it prints each selected path" \
        'contains "${OUT}" "bin/a" && contains "${OUT}" "lib/x/deep/f"'
    assert "  ... and it does not print an unselected path" '! contains "${OUT}" "bin/b"'
    assert "  ... and it pushes nothing" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_dry_run_reports_refusal_and_selection() {
    bold "case: a dry run with a denylist hit reports both"; echo
    make_case dryhit
    src_file bin/a "leak ${SECRET}"$'\n'
    src_file bin/ok 'fine'
    src_allow workflows bin/a bin/ok
    release_now
    run_tool -n workflows "${SHA}"
    assert "Given a selected file with a denylist hit, When run with -n, Then the exit is 1" \
        '[ "${RC}" -eq 1 ]'
    assert "  ... and it names the refusal file:line" 'contains "${OUT}" "bin/a:1"'
    assert "  ... and it still prints the selection" 'contains "${OUT}" "bin/ok"'
    assert "  ... and it pushes nothing, printing no denylisted text" \
        '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ] && ! contains_ci "${OUT}" "${SECRET}"'
}

case_dry_run_lists_every_refusal() {
    bold "case: a dry run lists every refusal, not just the first"; echo
    make_case drymulti
    printf 'secret.bin filter=git-crypt diff=git-crypt\n' > "${SRC}/.gitattributes"
    src_file secret.bin 'ciphertext stand-in'
    src_file bin/a "leak ${SECRET}"$'\n'
    src_allow workflows bin/a secret.bin bin/renamed-away
    release_now
    run_tool -n workflows "${SHA}"
    assert "Given a denylist hit, an encrypted file and a stale line, When run with -n, Then the exit is 1" \
        '[ "${RC}" -eq 1 ]'
    assert "  ... and the output names the denylist hit, the encrypted file and the stale line" \
        'contains "${OUT}" "bin/a:1" && contains "${OUT}" "secret.bin" && contains "${OUT}" "bin/renamed-away"'
    assert "  ... and nothing is pushed" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_empty_allow_list_does_nothing() {
    bold "case: an empty allow-list publishes nothing and never contacts the remote"; echo
    make_case empty
    src_file bin/a 'x'
    src_allow workflows '# nothing yet' ''
    release_now
    REMOTE="${WORKROOT}/empty/no-such-remote.git"
    run_tool workflows "${SHA}"
    assert "Given an allow-list of only comments and blanks, When published, Then the exit is 0" \
        '[ "${RC}" -eq 0 ]'
    assert "  ... and it says there is nothing to publish" 'contains_ci "${OUT}" "nothing to publish"'
    assert "  ... and the nonexistent remote was never created" '[ ! -e "${REMOTE}" ]'
}

case_push_failure_exits_1() {
    bold "case: a push failure exits 1"; echo
    make_case pushfail
    src_file bin/a 'x'
    src_allow workflows bin/a
    release_now
    printf '#!/bin/sh\nexit 1\n' > "${REMOTE}/hooks/pre-receive"
    chmod +x "${REMOTE}/hooks/pre-receive"
    run_tool workflows "${SHA}"
    assert "Given a remote that rejects the push, When published, Then the exit is 1 and the target is unchanged" \
        '[ "${RC}" -eq 1 ] && [ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_usage_errors() {
    bold "case: usage errors exit 2"; echo
    make_case usage
    src_file bin/a 'x'
    src_allow workflows bin/a
    release_now
    run_tool
    assert "Given no arguments, When run, Then the exit is 2" '[ "${RC}" -eq 2 ]'
    run_tool workflows
    assert "Given a target and no sha, When run, Then the exit is 2" '[ "${RC}" -eq 2 ]'
    run_tool no-such-target "${SHA}"
    assert "Given an unknown target, When run, Then the exit is 2 and nothing is pushed" \
        '[ "${RC}" -eq 2 ] && [ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
    run_tool -z workflows "${SHA}"
    assert "Given an unknown flag, When run, Then the exit is 2" '[ "${RC}" -eq 2 ]'
}

# --- Cases beyond the design's table: the refusal rules and their edges ---

# with_env <VAR=value>... -- run the tool with extra environment: TOOL becomes
# a wrapper that sets it and execs the real tool. without_env restores TOOL.
REAL_TOOL="${TOOL}"
with_env() {
    local wrap="${WORKROOT}/wrap-${RANDOM}"
    printf '#!/bin/sh\nexec env %s "%s" "$@"\n' "$*" "${REAL_TOOL}" > "${wrap}"
    chmod +x "${wrap}"
    TOOL="${wrap}"
}
without_env() { TOOL="${REAL_TOOL}"; }

# every extra workflow form the recognizer handles, accepted and refused.
case_workflow_recognizer_forms() {
    bold "case: the workflow recognizer accepts only the forms it fully understands"; echo
    workflow_case "with on: [workflow_call]" $'on: [workflow_call]\njobs: {}\n' ok
    workflow_case "with a quoted on key" $'"on":\n  workflow_call:\njobs: {}\n' ok
    workflow_case "with comments around workflow_call" \
        $'# header\non: # why\n  # note\n  workflow_call: # reusable\n    inputs: {}\njobs: {}\n' ok
    workflow_case "with a leading document marker" $'---\non: workflow_call\njobs: {}\n' ok
    workflow_case "with no on key" $'name: x\njobs: {}\n' refuse
    workflow_case "with two on keys" $'on: workflow_call\n"on": push\njobs: {}\n' refuse
    workflow_case "with a key spelled On" $'On: push\non: workflow_call\njobs: {}\n' refuse
    workflow_case "with a tab in the indentation" $'on:\n\tworkflow_call:\njobs: {}\n' refuse
    workflow_case "with an anchor on the on value" $'on: &t workflow_call\njobs: {}\n' refuse
    workflow_case "with an alias as the on value" $'x: &a 1\non: *a\njobs: {}\n' refuse
    workflow_case "with on as a block sequence" $'on:\n  - workflow_call\njobs: {}\n' refuse
    workflow_case "with an on value that continues on the next line" \
        $'on: workflow_call\n  push\njobs: {}\n' refuse
    workflow_case "with a second document" $'on: workflow_call\n---\non: push\n' refuse
    workflow_case "with an empty on" $'on:\njobs: {}\n' refuse
    workflow_case "with a trigger indented less than the first child" \
        $'on:\n    workflow_call:\n  push:\njobs: {}\n' refuse
    workflow_case "with a multi-line quoted top-level value" \
        $'on: workflow_call\nname: "a\nb"\njobs: {}\n' refuse
    workflow_case "with an empty file" '' refuse
}

case_workflow_symlink_refused() {
    bold "case: a symlink under .github/workflows is never a workflow"; echo
    make_case wflink
    src_file lib/real.yml $'on: workflow_call\njobs: {}\n'
    mkdir -p "${SRC}/.github/workflows"
    ln -s ../../lib/real.yml "${SRC}/.github/workflows/w.yml"
    src_allow workflows lib/real.yml .github/workflows/w.yml
    release_now
    run_tool workflows "${SHA}"
    assert "Given a selected symlink named like a workflow, When workflows is published, Then it is refused and named" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" ".github/workflows/w.yml" && contains_ci "${OUT}" "workflow-trigger"'
}

case_scan_ignores_the_opt_out() {
    bold "case: TDS_BLEED_GUARD=0 and bleedguard.enabled=false do not disable the scan"; echo
    make_case optout
    src_file bin/a "leak ${SECRET}"$'\n'
    src_allow workflows bin/a
    release_now
    printf '[bleedguard]\n\tenabled = false\n' > "${GITCONFIG}"
    with_env TDS_BLEED_GUARD=0
    run_tool workflows "${SHA}"
    without_env
    assert "Given both opt-outs, When a selected file hits the denylist, Then it is still refused" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "bin/a:1"'
    assert "  ... and nothing is pushed" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_binary_files_are_scanned() {
    bold "case: binary files are scanned in full"; echo
    make_case binary
    printf 'head\0\0tail %s\0end' "${SECRET}" > "${SRC}/blob.bin"
    printf 'one\0\ntwo\n%s\n' "${SECRET}" > "${SRC}/two.bin"
    src_allow workflows blob.bin two.bin
    release_now
    run_tool workflows "${SHA}"
    assert "Given NUL bytes before a denylist entry, When published, Then the file is refused at its line" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "blob.bin:1" && contains "${OUT}" "two.bin:3"'
    assert "  ... and nothing is pushed, no text printed" \
        '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ] && ! contains_ci "${OUT}" "${SECRET}"'
}

case_name_hit_is_redacted() {
    bold "case: a selected file name that holds an entry is refused and redacted"; echo
    make_case namehit
    src_file "bin/x-zzprivatefixture-y" 'harmless'
    src_allow workflows 'bin/*'
    release_now
    run_tool workflows "${SHA}"
    assert "Given a selected path whose name holds an entry in another case, When published, Then it is refused as a name match" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "file name matches denylist entry"'
    assert "  ... and the name is redacted everywhere, and nothing is pushed" \
        'contains "${OUT}" "[redacted]" && [ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ] && ! contains_ci "${OUT}" "${SECRET}"'
}

case_empty_denylist_is_fine() {
    bold "case: a denylist with no entries does not refuse"; echo
    make_case emptydeny
    src_file bin/a 'x'
    src_allow workflows bin/a
    release_now
    printf '# nothing private yet\n\n' > "${DENYLIST_PATH}"
    run_tool workflows "${SHA}"
    assert "Given a readable denylist of only comments, When published, Then it is published" \
        '[ "${RC}" -eq 0 ] && remote_has bin/a'
}

case_reads_the_released_tree_not_the_work_tree() {
    bold "case: allow-list and attributes come from the released commit"; echo
    make_case fromtree
    src_file bin/a 'a'
    src_file bin/b 'b'
    printf 'secret.bin filter=git-crypt\n' > "${SRC}/.gitattributes"
    src_file secret.bin 'ciphertext stand-in'
    src_allow workflows bin/a secret.bin
    release_now
    printf 'bin/b\n' >> "${SRC}/publish/workflows.allow"
    : > "${SRC}/.gitattributes"
    run_tool workflows "${SHA}"
    assert "Given a work tree that drops the git-crypt attribute, When published, Then the committed attribute still refuses" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "secret.bin" && contains_ci "${OUT}" "git-crypt"'
    make_case fromtree2
    src_file bin/a 'a'
    src_file bin/b 'b'
    src_allow workflows bin/a
    release_now
    printf 'bin/b\n' >> "${SRC}/publish/workflows.allow"
    run_tool workflows "${SHA}"
    assert "Given a work-tree allow-list edit that is not committed, When published, Then only the committed list is published" \
        '[ "${RC}" -eq 0 ] && remote_has bin/a && ! remote_has bin/b'
}

case_git_crypt_named_key_refuses() {
    bold "case: a git-crypt named-key filter refuses too"; echo
    make_case cryptkey
    printf '*.bin filter=git-crypt-mykey diff=git-crypt-mykey\n' > "${SRC}/.gitattributes"
    src_file secret.bin 'ciphertext stand-in'
    src_allow workflows secret.bin
    release_now
    run_tool workflows "${SHA}"
    assert "Given filter=git-crypt-mykey on a selected file, When published, Then it is refused" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "secret.bin"'
    assert "  ... and nothing is pushed" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_missing_allow_list_refuses() {
    bold "case: a commit with no allow-list refuses"; echo
    make_case noallow
    src_file bin/a 'x'
    release_now
    run_tool workflows "${SHA}"
    assert "Given no publish/workflows.allow at the released commit, When published, Then the file is named" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "publish/workflows.allow"'
    assert "  ... and nothing is pushed" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_bad_allow_lines_refuse() {
    bold "case: allow-list lines that could be options, magic or negation refuse"; echo
    make_case badlines
    src_file bin/a 'x'
    src_allow workflows bin/a '!bin/a' '--help' ':(top)bin/a' '/etc/passwd' '../x' 'bin/../bin/a' './bin/a'
    release_now
    run_tool workflows "${SHA}"
    assert "Given seven unusable lines, When published, Then each is named by line number" \
        'contains "${OUT}" "workflows.allow:2" && contains "${OUT}" "workflows.allow:3" && contains "${OUT}" "workflows.allow:4" && contains "${OUT}" "workflows.allow:5" && contains "${OUT}" "workflows.allow:6" && contains "${OUT}" "workflows.allow:7" && contains "${OUT}" "workflows.allow:8"'
    assert "  ... and nothing is pushed" '[ "${RC}" -eq 1 ] && [ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_symlink_escapes_refuse() {
    bold "case: absolute, escaping, directory and chained symlinks refuse"; echo
    make_case linkbad
    src_file bin/b 'file'
    src_file dir/f 'in a dir'
    ln -s /etc/passwd "${SRC}/abs"
    ln -s ../../outside "${SRC}/bin/esc"
    ln -s ../dir "${SRC}/bin/todir"
    ln -s b "${SRC}/bin/hop"
    ln -s hop "${SRC}/bin/chain"
    src_allow workflows bin/b dir/f abs bin/esc bin/todir bin/hop bin/chain
    release_now
    run_tool workflows "${SHA}"
    assert "Given absolute, escaping, directory and chained links, When published, Then the first three and the chain are named" \
        'contains "${OUT}" "symlink-escape: abs" && contains "${OUT}" "symlink-escape: bin/esc" && contains "${OUT}" "symlink-escape: bin/todir" && contains "${OUT}" "symlink-escape: bin/chain"'
    assert "  ... and the sound link (to a selected regular file) is not named" \
        '! contains "${OUT}" "symlink-escape: bin/hop"'
    assert_refused
}

case_symlink_up_and_over_publishes() {
    bold "case: a relative link that climbs and descends within the repo publishes"; echo
    make_case linkup
    src_file bin/b 'selected'
    mkdir -p "${SRC}/lib/deep"
    ln -s ../../bin/b "${SRC}/lib/deep/l"
    src_allow workflows bin/b lib/deep/l
    release_now
    run_tool workflows "${SHA}"
    assert "Given lib/deep/l -> ../../bin/b with bin/b selected, When published, Then it is published as a symlink" \
        '[ "${RC}" -eq 0 ] && [ "$(remote_mode lib/deep/l)" = 120000 ]'
}

case_submodule_refuses() {
    bold "case: a selected gitlink refuses"; echo
    make_case submod
    src_file bin/a 'x'
    src_allow workflows bin/a vendor
    # release_now would `git add -A` the gitlink away (no work-tree directory).
    git -C "${SRC}" add bin publish
    git -C "${SRC}" update-index --add --cacheinfo "160000,$(git -C "${SRC}" hash-object -t blob /dev/null),vendor"
    git -C "${SRC}" commit -q -m "with a gitlink"
    git -C "${SRC}" branch -f release HEAD
    SHA="$(git -C "${SRC}" rev-parse HEAD)"
    run_tool workflows "${SHA}"
    assert "Given a selected submodule path, When published, Then it is refused as a submodule" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "submodule: vendor"'
    assert "  ... and nothing is pushed" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_unsafe_path_refuses() {
    bold "case: a selected path with a newline refuses"; echo
    make_case unsafe
    src_file bin/ok 'x'
    src_file "bin/a"$'\n'"b" 'x'
    src_allow workflows 'bin/*'
    release_now
    run_tool workflows "${SHA}"
    assert "Given a path holding a newline, When published, Then it is refused as unsafe" \
        '[ "${RC}" -eq 1 ] && contains "${OUT}" "unsafe-path"'
    assert "  ... and nothing is pushed" '[ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
}

case_export_attributes_do_not_alter_bytes() {
    bold "case: export-subst and export-ignore never change what is published"; echo
    make_case exportattr
    src_file .gitattributes $'bin/a export-subst\nbin/ig export-ignore\n'
    src_file bin/a '$Format:%H$'
    src_file bin/ig 'selected despite export-ignore'
    src_allow workflows .gitattributes bin/a bin/ig
    release_now
    run_tool workflows "${SHA}"
    assert "Given export-subst and export-ignore attributes, When published, Then every blob equals the released one" \
        '[ "${RC}" -eq 0 ] && [ "$(remote_oid bin/a)" = "$(src_oid bin/a)" ] && [ "$(remote_oid bin/ig)" = "$(src_oid bin/ig)" ] && [ "$(remote_oid .gitattributes)" = "$(src_oid .gitattributes)" ]'
}

case_abbreviated_sha_publishes_full_message() {
    bold "case: an abbreviated sha publishes with the full sha in the message"; echo
    make_case shortsha
    src_file bin/a 'x'
    src_allow workflows bin/a
    release_now
    run_tool workflows "${SHA:0:10}"
    assert "Given a 10-digit prefix of the release head, When published, Then the message carries the full sha" \
        '[ "${RC}" -eq 0 ] && [ "$(remote_msg)" = "release ${SHA}" ]'
}

case_empty_target_remote_gets_first_commit() {
    bold "case: a target with no commits yet receives a parentless first commit"; echo
    make_case firstpush
    src_file bin/a 'x'
    src_allow workflows bin/a
    release_now
    rm -rf "${REMOTE}"
    git init -q --bare -b main "${REMOTE}"
    run_tool workflows "${SHA}"
    assert "Given an empty target repository, When published, Then main holds one commit with the selection" \
        '[ "${RC}" -eq 0 ] && [ "$(remote_count)" -eq 1 ] && [ "$(remote_paths)" = "bin/a " ] && [ "$(remote_msg)" = "release ${SHA}" ]'
}

case_no_temp_dir_survives() {
    bold "case: no scratch directory survives, on any path"; echo
    make_case scratch
    src_file bin/a 'x'
    src_file bin/bad "leak ${SECRET}"
    src_allow workflows bin/a
    release_now
    local tmp="${WORKROOT}/scratch/tmp"
    mkdir -p "${tmp}"
    with_env "TMPDIR=${tmp}"
    run_tool workflows "${SHA}"
    assert "Given a publication, When it succeeds, Then the scratch directory is gone" \
        '[ "${RC}" -eq 0 ] && [ -z "$(ls -A "${tmp}")" ]'
    run_tool -n workflows "${SHA}"
    assert "  ... a dry run leaves none" '[ -z "$(ls -A "${tmp}")" ]'
    src_allow workflows bin/a bin/bad
    release_now
    run_tool workflows "${SHA}"
    assert "  ... a refusal leaves none" '[ "${RC}" -eq 1 ] && [ -z "$(ls -A "${tmp}")" ]'
    src_allow workflows bin/a
    src_file bin/a 'y'
    release_now
    printf '#!/bin/sh\nexit 1\n' > "${REMOTE}/hooks/pre-receive"
    chmod +x "${REMOTE}/hooks/pre-receive"
    run_tool workflows "${SHA}"
    assert "  ... a failed push leaves none" '[ "${RC}" -eq 1 ] && [ -z "$(ls -A "${tmp}")" ]'
    without_env
}

# The bot path, without a network: a fake asbot stands in, and git's URL
# rewriting sends the GitHub URL to the local bare repo, so a routing bug
# fails the test rather than reaching GitHub.
make_fake_asbot() {
    local fake="$1" local_url="$2" log="$3"
    cat > "${fake}" <<FAKE
#!/bin/sh
printf '%s\n' "\$*" >> "${log}"
# argv: env GIT_CONFIG_GLOBAL=.. GIT_CONFIG_NOSYSTEM=.. git <args...>
[ "\$1" = env ] || exit 3
shift 3
[ "\$1" = git ] || exit 3
shift
exec env GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \\
    GIT_AUTHOR_NAME=9atatimer-bot GIT_COMMITTER_NAME=9atatimer-bot \\
    git -c "url.${local_url}.insteadOf=https://github.com/9atatimer/workflows.git" "\$@"
FAKE
    chmod +x "${fake}"
}

case_bot_path_runs_through_asbot() {
    bold "case: without TDS_PUBLIC_REMOTE the clone, commit and push run through asbot"; echo
    make_case botpath
    src_file bin/a 'x'
    src_allow workflows bin/a
    release_now
    local fake="${WORKROOT}/botpath/asbot" log="${WORKROOT}/botpath/asbot.log" real_remote="${REMOTE}"
    make_fake_asbot "${fake}" "${real_remote}" "${log}"
    printf '[url "%s/nowhere/"]\n\tinsteadOf = https://github.com/\n' "${WORKROOT}" > "${GITCONFIG}"
    REMOTE=""
    with_env "TDS_PUBLIC_ASBOT=${fake}"
    run_tool workflows "${SHA}"
    without_env
    REMOTE="${real_remote}"
    assert "Given a fake asbot, When published with no TDS_PUBLIC_REMOTE, Then the exit is 0 and the target gained the commit" \
        '[ "${RC}" -eq 0 ] && remote_has bin/a && [ "$(remote_msg)" = "release ${SHA}" ]'
    assert "  ... and the commit is the bot's, not the ambient identity's" \
        '[ "$(git -C "${REMOTE}" log -1 --format=%an HEAD)" = 9atatimer-bot ]'
    assert "  ... and asbot ran the clone of the GitHub HTTPS URL, the commit and the push" \
        'grep -q "clone .*https://github.com/9atatimer/workflows.git" "${log}" && grep -q "commit-tree" "${log}" && grep -q " push " "${log}"'
    assert "  ... and the credential is the bot token alone (no user git config)" \
        'grep -q "credential.helper=!gh auth git-credential" "${log}" && grep -q "GIT_CONFIG_GLOBAL=/dev/null" "${log}"'
}

case_asbot_failure_is_a_failure() {
    bold "case: an asbot that refuses fails the run, never falls back to the owner"; echo
    make_case botfail
    src_file bin/a 'x'
    src_allow workflows bin/a
    release_now
    local fake="${WORKROOT}/botfail/asbot" log="${WORKROOT}/botfail/asbot.log"
    printf '#!/bin/sh\necho "$*" >> "%s"\nexit 1\n' "${log}" > "${fake}"
    chmod +x "${fake}"
    printf '[url "%s/nowhere/"]\n\tinsteadOf = https://github.com/\n' "${WORKROOT}" > "${GITCONFIG}"
    local real_remote="${REMOTE}"
    REMOTE=""
    with_env "TDS_PUBLIC_ASBOT=${fake}"
    run_tool workflows "${SHA}"
    assert "Given an asbot that exits 1, When published, Then the exit is 1 and asbot was the only thing tried" \
        '[ "${RC}" -eq 1 ] && [ "$(wc -l < "${log}" | tr -d " ")" -eq 1 ]'
    with_env "TDS_PUBLIC_ASBOT=${WORKROOT}/botfail/missing"
    run_tool workflows "${SHA}"
    without_env
    REMOTE="${real_remote}"
    assert "Given an asbot that does not exist, When published, Then the exit is 1 and it says asbot" \
        '[ "${RC}" -eq 1 ] && contains_ci "${OUT}" "asbot"'
    assert "  ... and the target is untouched" '[ "$(remote_head)" = "${INITIAL_HEAD}" ]'
}

case_bleed_guard_and_tds_public_share_one_matcher() {
    bold "case: bleed-guard and tds-public source the same matcher library"; echo
    assert "Given the two tools, When the matcher is looked for, Then both source lib/bleed-match.sh and neither defines match_records" \
        'grep -q "bleed-match.sh" "${REPO_DIR}/bin/bleed-guard" && grep -q "bleed-match.sh" "${TOOL}" && ! grep -q "^match_records()" "${REPO_DIR}/bin/bleed-guard" "${TOOL}"'
}

# --- Fail closed: a check that cannot run is a refusal ---

# make_shim <tool> <marker> -- a directory holding a <tool> that exits 1 when
# its arguments contain <marker> (always, when <marker> is empty) and otherwise
# runs the real tool, so only the tool's own use of it breaks. Echoes the dir.
make_shim() {
    local tool="$1" marker="$2" dir real
    dir="${WORKROOT}/shim-${tool}-${RANDOM}"
    real="$(command -v "${tool}")"
    mkdir -p "${dir}"
    {
        printf '#!/bin/sh\n'
        if [ -z "${marker}" ]; then
            printf 'exit 1\n'
        else
            printf 'case "$*" in *%s*) exit 1 ;; esac\nexec "%s" "$@"\n' "${marker}" "${real}"
        fi
    } > "${dir}/${tool}"
    chmod +x "${dir}/${tool}"
    printf '%s\n' "${dir}"
}

# shim_case <label> <tool> <marker> -- publish a clean selection and one file
# holding the secret with <tool> broken for the tool alone.
shim_case() {
    local label="$1" tool="$2" marker="$3" dir
    make_case "shim-${tool}-${RANDOM}"
    src_file bin/a 'clean'
    src_file bin/leak "leak ${SECRET}"$'\n'
    ln -s a "${SRC}/bin/l"
    src_allow workflows bin/a bin/leak bin/l
    release_now
    dir="$(make_shim "${tool}" "${marker}")"
    with_env "PATH='${dir}:${PATH}'"
    run_tool workflows "${SHA}"
    without_env
    assert "Given ${label}, When published, Then the exit is 1 and nothing is pushed" \
        '[ "${RC}" -eq 1 ] && [ "${REMOTE_BEFORE}" = "${REMOTE_AFTER}" ]'
    assert "  ... and an internal refusal says a check could not run" \
        'contains "${OUT}" "refused: internal:"'
    assert "  ... and the secret is not printed" '! contains_ci "${OUT}" "${SECRET}"'
}

case_broken_machinery_refuses() {
    bold "case: a check whose own machinery fails is a refusal, never a pass"; echo
    shim_case "an awk that always fails" awk ""
    shim_case "an awk that fails only for the denylist matcher" awk "matches denylist entry"
    shim_case "a sort that fails" sort ""
    shim_case "a tr that fails" tr ""
    shim_case "a sed that fails" sed ""
    shim_case "a git that cannot read the released tree" git "read-tree"
    shim_case "a git that cannot list the tree" git "ls-files"
    shim_case "a git that cannot read blobs" git "cat-file"
    shim_case "a wc that fails" wc ""
    shim_case "a cat that fails" cat ""
}

# --- Main ---

main() {
    WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/tds-public-test.XXXXXX")"

    case_publishes_allowlisted_tree
    case_unlisted_file_never_published
    case_denylist_hit_refuses
    case_denylist_via_git_config
    case_no_denylist_refuses
    case_stale_allow_line_refuses
    case_workflow_triggers
    case_trigger_rule_only_for_workflows_target
    case_mirror_never_receives_github
    case_git_crypt_file_refuses
    case_symlink_to_unselected_refuses
    case_symlink_to_selected_publishes
    case_unchanged_release_adds_no_commit
    case_second_publish_chains_commits
    case_only_released_commit_published
    case_dry_run_publishes_nothing
    case_dry_run_reports_refusal_and_selection
    case_dry_run_lists_every_refusal
    case_empty_allow_list_does_nothing
    case_push_failure_exits_1
    case_usage_errors
    case_workflow_recognizer_forms
    case_workflow_symlink_refused
    case_scan_ignores_the_opt_out
    case_binary_files_are_scanned
    case_name_hit_is_redacted
    case_empty_denylist_is_fine
    case_reads_the_released_tree_not_the_work_tree
    case_git_crypt_named_key_refuses
    case_missing_allow_list_refuses
    case_bad_allow_lines_refuse
    case_symlink_escapes_refuse
    case_symlink_up_and_over_publishes
    case_submodule_refuses
    case_unsafe_path_refuses
    case_export_attributes_do_not_alter_bytes
    case_abbreviated_sha_publishes_full_message
    case_empty_target_remote_gets_first_commit
    case_no_temp_dir_survives
    case_bot_path_runs_through_asbot
    case_asbot_failure_is_a_failure
    case_bleed_guard_and_tds_public_share_one_matcher
    case_broken_machinery_refuses

    printf '\n%d run, %d passed, %d failed\n' "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
