#!/usr/bin/env bash
# smoketest_claude_as_bot.sh -- bin/claude-as-bot runs an agent session as
# the machine account: GitHub over HTTPS with the bot's token, commits under
# the bot's name, and never the owner's SSH key.
#
# Hermetic: --print-env shows the environment the session would get, with
# the token's reference and never its value, so no 1Password and no network.
#
# Usage: ./test/smoketest_claude_as_bot.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
LAUNCHER="${REPO_DIR}/bin/claude-as-bot"

# --- Test harness ---

pass=0
fail=0

check() {
    local name=$1 haystack=$2 needle=$3
    if grep -qF -- "$needle" <<<"$haystack"; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        echo "FAIL: $name: missing '$needle'" >&2
    fi
}

refuse() {
    local name=$1 haystack=$2 needle=$3
    if grep -qF -- "$needle" <<<"$haystack"; then
        fail=$((fail + 1))
        echo "FAIL: $name: unexpected '$needle'" >&2
    else
        pass=$((pass + 1))
    fi
}

# --- Cases ---

test_the_session_env_is_the_bot() {
    local out
    out=$(TDS_BOT_GH_TOKEN_REF='op://vault/item/credential' "$LAUNCHER" --print-env)
    check "token comes from the reference" "$out" 'GH_TOKEN=op://vault/item/credential'
    check "author is the bot" "$out" 'GIT_AUTHOR_NAME=9atatimer-bot'
    check "committer is the bot" "$out" 'GIT_COMMITTER_NAME=9atatimer-bot'
    check "author email is the bot's no-reply" "$out" 'GIT_AUTHOR_EMAIL=341954893+9atatimer-bot@users.noreply.github.com'
    check "ssh remotes are rewritten to https" "$out" 'GIT_CONFIG_KEY_0=url.https://github.com/.insteadOf'
    check "the rewrite covers git@github.com:" "$out" 'GIT_CONFIG_VALUE_0=git@github.com:'
    check "the rewrite covers ssh://git@github.com/" "$out" 'GIT_CONFIG_VALUE_1=ssh://git@github.com/'
    check "two rewrite entries" "$out" 'GIT_CONFIG_COUNT=2'
}

test_no_reference_is_refused() {
    local rc=0
    TDS_BOT_GH_TOKEN_REF='' "$LAUNCHER" --print-env >/dev/null 2>&1 || rc=$?
    if [ "$rc" -ne 0 ]; then pass=$((pass + 1)); else
        fail=$((fail + 1)); echo "FAIL: an unset reference must refuse" >&2
    fi
}

test_a_literal_token_is_refused() {
    local rc=0 out
    out=$(TDS_BOT_GH_TOKEN_REF='ghp_notareference' "$LAUNCHER" --print-env 2>&1) || rc=$?
    if [ "$rc" -ne 0 ]; then pass=$((pass + 1)); else
        fail=$((fail + 1)); echo "FAIL: a non-op:// value must refuse" >&2
    fi
    refuse "a refused token is never echoed" "$out" 'ghp_notareference'
}

# --- Main ---

test_the_session_env_is_the_bot
test_no_reference_is_refused
test_a_literal_token_is_refused

echo "smoketest_claude_as_bot: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
