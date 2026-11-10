#!/usr/bin/env bash
# smoketest_asbot.sh -- bin/asbot runs one command as 9atatimer-bot from a
# session running as the owner, and runs nothing when it cannot prove the
# identity switched.
#
# Hermetic: fake `claude-as-bot`, `op`, `gh` and a recording command go
# first on PATH, so no 1Password and no network.
#
# Usage: ./test/smoketest_asbot.sh

set -euo pipefail

# The cases set the variable themselves; the caller's must not leak in.
unset TDS_BOT_GH_TOKEN_REF


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
ASBOT="${REPO_DIR}/bin/asbot"

# --- Test harness ---

pass=0
fail=0

ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

# --- Fixtures ---

SCRATCH=""

cleanup() {
    [[ -n ${SCRATCH} ]] && rm -rf "${SCRATCH}"
}

make_fakes() {
    SCRATCH="$(mktemp -d)"
    trap cleanup EXIT
    mkdir -p "${SCRATCH}/bin"

    # claude-as-bot: prints a session env, or fails when FAKE_CAB_FAIL is set.
    cat >"${SCRATCH}/bin/claude-as-bot" <<'SH'
#!/usr/bin/env bash
[[ -n ${FAKE_CAB_FAIL:-} ]] && { echo "TDS_BOT_GH_TOKEN_REF unset" >&2; exit 1; }
[[ $1 == --print-env ]] || exit 9
ref="op://vault/item/credential"
[[ -n ${FAKE_CAB_KEYCHAIN:-} ]] && ref="keychain:tds.github.9atatimer-bot"
printf '%s\n' "GH_TOKEN=${ref}" "GIT_AUTHOR_NAME=9atatimer-bot"
SH

    # security: `find-generic-password -s S -a A -w` prints FAKE_KEYCHAIN_TOKEN
    # for the bot's item, or fails when it is unset. Every argv is logged.
    cat >"${SCRATCH}/bin/security" <<'SH'
#!/usr/bin/env bash
echo "security $*" >>"${FAKE_LOG}.argv"
[[ "$*" == "find-generic-password -s tds.github.9atatimer-bot -a 9atatimer-bot -w" ]] || exit 9
[[ -n ${FAKE_KEYCHAIN_TOKEN:-} ]] || exit 44
echo "${FAKE_KEYCHAIN_TOKEN}"
SH

    # op: `op run --env-file F -- cmd...`, resolving op:// values to a fake token.
    cat >"${SCRATCH}/bin/op" <<'SH'
#!/usr/bin/env bash
echo op >>"${FAKE_LOG}"
[[ $1 == run && $2 == --env-file ]] || exit 9
file=$3; shift 3; [[ $1 == -- ]] && shift
while IFS='=' read -r k v; do
    [[ -z $k ]] && continue
    [[ $v == op://* ]] && v=fake-token
    export "$k=$v"
done <"$file"
exec "$@"
SH

    # gh: `gh api user --jq .login` answers FAKE_LOGIN, or fails (a 401)
    # when GH_TOKEN is FAKE_REJECTED_TOKEN.
    cat >"${SCRATCH}/bin/gh" <<'SH'
#!/usr/bin/env bash
[[ "$*" == "api user --jq .login" ]] || exit 9
[[ -n ${FAKE_REJECTED_TOKEN:-} && ${GH_TOKEN:-} == "${FAKE_REJECTED_TOKEN}" ]] && { echo "HTTP 401: Bad credentials" >&2; exit 1; }
echo "${FAKE_LOGIN}"
SH

    # record: writes its argv and the token it saw.
    cat >"${SCRATCH}/bin/record" <<'SH'
#!/usr/bin/env bash
printf 'ran token=%s author=%s args=' "${GH_TOKEN:-}" "${GIT_AUTHOR_NAME:-}" >>"${FAKE_LOG}"
printf '[%s]' "$@" >>"${FAKE_LOG}"
echo >>"${FAKE_LOG}"
SH
    chmod +x "${SCRATCH}/bin/"*
}

run_asbot() {
    : >"${SCRATCH}/log"
    : >"${SCRATCH}/log.argv"
    PATH="${SCRATCH}/bin:${PATH}" FAKE_LOG="${SCRATCH}/log" "$ASBOT" "$@"
}

# --- Cases ---

test_runs_the_command_as_the_bot() {
    local rc=0
    FAKE_LOGIN=9atatimer-bot run_asbot record "two words" plain >/dev/null 2>&1 || rc=$?
    if [[ $rc -eq 0 ]]; then ok; else bad "exit $rc running as the bot"; fi
    if grep -qF 'ran token=fake-token author=9atatimer-bot args=[two words][plain]' "${SCRATCH}/log"; then ok; else bad "command did not run with the bot env and verbatim args: $(cat "${SCRATCH}/log")"; fi
}

test_a_failed_switch_runs_nothing() {
    local rc=0
    FAKE_CAB_FAIL=1 FAKE_LOGIN=9atatimer-bot run_asbot record x >/dev/null 2>&1 || rc=$?
    if [[ $rc -ne 0 ]]; then ok; else bad "a failed claude-as-bot must fail"; fi
    if ! grep -q '^ran' "${SCRATCH}/log"; then ok; else bad "command ran after claude-as-bot failed"; fi
    if ! grep -q '^op' "${SCRATCH}/log"; then ok; else bad "op ran after claude-as-bot failed (fail-open)"; fi
}

test_the_wrong_login_runs_nothing() {
    local rc=0 err
    err=$(FAKE_LOGIN=the-owner run_asbot record x 2>&1 >/dev/null) || rc=$?
    if [[ $rc -ne 0 ]]; then ok; else bad "a non-bot login must fail"; fi
    if ! grep -q '^ran' "${SCRATCH}/log"; then ok; else bad "command ran as the-owner"; fi
    if grep -qF 'the-owner' <<<"$err"; then ok; else bad "refusal does not name the login it saw"; fi
}

test_the_keychain_needs_no_op() {
    local rc=0
    FAKE_CAB_KEYCHAIN=1 FAKE_KEYCHAIN_TOKEN=ghp_keychaintoken FAKE_LOGIN=9atatimer-bot \
        run_asbot record "two words" >/dev/null 2>&1 || rc=$?
    if [[ $rc -eq 0 ]]; then ok; else bad "exit $rc on the keychain path"; fi
    if grep -qF 'ran token=ghp_keychaintoken author=9atatimer-bot args=[two words]' "${SCRATCH}/log"; then ok; else bad "command did not run with the keychain token: $(cat "${SCRATCH}/log")"; fi
    if ! grep -q '^op' "${SCRATCH}/log"; then ok; else bad "op ran on the keychain path (a 1Password prompt)"; fi
    if ! grep -q ghp_keychaintoken "${SCRATCH}/log.argv"; then ok; else bad "the token reached an argv"; fi
}

test_the_keychain_path_checks_the_login() {
    local rc=0
    FAKE_CAB_KEYCHAIN=1 FAKE_KEYCHAIN_TOKEN=ghp_keychaintoken FAKE_LOGIN=the-owner \
        run_asbot record x >/dev/null 2>&1 || rc=$?
    if [[ $rc -ne 0 ]]; then ok; else bad "keychain path: a non-bot login must fail"; fi
    if ! grep -q '^ran' "${SCRATCH}/log"; then ok; else bad "keychain path: command ran as the-owner"; fi
}

test_an_unreadable_keychain_runs_nothing() {
    local rc=0
    FAKE_CAB_KEYCHAIN=1 FAKE_LOGIN=9atatimer-bot run_asbot record x >/dev/null 2>&1 || rc=$?
    if [[ $rc -ne 0 ]]; then ok; else bad "an unreadable keychain item must fail"; fi
    if ! grep -q '^ran' "${SCRATCH}/log"; then ok; else bad "command ran without a token"; fi
}

test_an_unreadable_keychain_falls_back_to_the_variable() {
    local rc=0 err
    err=$(FAKE_CAB_KEYCHAIN=1 FAKE_LOGIN=9atatimer-bot TDS_BOT_GH_TOKEN_REF=op://vault/item/credential \
        run_asbot record x 2>&1 >/dev/null) || rc=$?
    if [[ $rc -eq 0 ]]; then ok; else bad "unreadable keychain + variable must run, exit $rc"; fi
    if grep -qF 'ran token=fake-token' "${SCRATCH}/log"; then ok; else bad "fallback did not run with the 1Password token: $(cat "${SCRATCH}/log")"; fi
    if grep -qF 'seed-bot-token' <<<"$err"; then ok; else bad "fallback does not say to re-seed"; fi
}

test_a_rejected_keychain_token_falls_back() {
    local rc=0 err
    err=$(FAKE_CAB_KEYCHAIN=1 FAKE_KEYCHAIN_TOKEN=ghp_stale FAKE_REJECTED_TOKEN=ghp_stale FAKE_LOGIN=9atatimer-bot \
        TDS_BOT_GH_TOKEN_REF=op://vault/item/credential run_asbot record x 2>&1 >/dev/null) || rc=$?
    if [[ $rc -eq 0 ]]; then ok; else bad "rejected keychain token + variable must run, exit $rc"; fi
    if grep -qF 'ran token=fake-token' "${SCRATCH}/log"; then ok; else bad "rejected token: fallback did not run with the 1Password token: $(cat "${SCRATCH}/log")"; fi
    if grep -qF 'seed-bot-token' <<<"$err"; then ok; else bad "rejected token: does not say to re-seed"; fi
}

test_a_rejected_keychain_token_without_a_variable_refuses() {
    local rc=0 err
    err=$(FAKE_CAB_KEYCHAIN=1 FAKE_KEYCHAIN_TOKEN=ghp_stale FAKE_REJECTED_TOKEN=ghp_stale FAKE_LOGIN=9atatimer-bot \
        run_asbot record x 2>&1 >/dev/null) || rc=$?
    if [[ $rc -ne 0 ]]; then ok; else bad "rejected token, no variable: must refuse"; fi
    if ! grep -q '^ran' "${SCRATCH}/log"; then ok; else bad "rejected token, no variable: command ran"; fi
    if grep -qF 'seed-bot-token' <<<"$err"; then ok; else bad "rejected token, no variable: does not say to re-seed"; fi
}

test_a_keychain_wrong_login_never_falls_back() {
    local rc=0
    FAKE_CAB_KEYCHAIN=1 FAKE_KEYCHAIN_TOKEN=ghp_owner FAKE_LOGIN=the-owner \
        TDS_BOT_GH_TOKEN_REF=op://vault/item/credential run_asbot record x >/dev/null 2>&1 || rc=$?
    if [[ $rc -ne 0 ]]; then ok; else bad "keychain wrong login must refuse"; fi
    if ! grep -q '^op' "${SCRATCH}/log"; then ok; else bad "a wrong login fell back to op"; fi
    if ! grep -q '^ran' "${SCRATCH}/log"; then ok; else bad "keychain wrong login: command ran"; fi
}

test_no_command_is_usage() {
    local rc=0
    FAKE_LOGIN=9atatimer-bot run_asbot >/dev/null 2>&1 || rc=$?
    if [[ $rc -eq 2 ]]; then ok; else bad "no command must exit 2, got $rc"; fi
}

# --- Main ---

main() {
    make_fakes
    test_runs_the_command_as_the_bot
    test_a_failed_switch_runs_nothing
    test_the_wrong_login_runs_nothing
    test_the_keychain_needs_no_op
    test_the_keychain_path_checks_the_login
    test_an_unreadable_keychain_runs_nothing
    test_an_unreadable_keychain_falls_back_to_the_variable
    test_a_rejected_keychain_token_falls_back
    test_a_rejected_keychain_token_without_a_variable_refuses
    test_a_keychain_wrong_login_never_falls_back
    test_no_command_is_usage
    echo "asbot: ${pass} passed, ${fail} failed"
    [[ ${fail} -eq 0 ]]
}

main "$@"
