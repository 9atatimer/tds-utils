#!/usr/bin/env bash
# smoketest_claude_as_bot.sh -- bin/claude-as-bot runs an agent session as
# the machine account: GitHub over HTTPS with the bot's token, commits under
# the bot's name, and never the owner's SSH key.
#
# Hermetic: --print-env shows the environment the session would get, with
# the token's reference and never its value; the launch cases put a fake
# `op` (resolves the reference to a fake token, then runs its command) and a
# recording `clai`/`claude` first on PATH, so no 1Password and no network.
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

# --- Launch fixtures ---

SCRATCH=""

cleanup() {
    if [ -n "${SCRATCH}" ]; then
        rm -rf "${SCRATCH}"
    fi
}

# A fake `op`: `op run --env-file F -- cmd args` exports F's lines, swaps
# any op:// value for a fake token, records F's path, and runs cmd.
write_fake_op() {
    local dir=$1
    cat >"${dir}/op" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
[ "$1" = run ] && [ "$2" = --env-file ] && [ "$4" = -- ] || { echo "fake op: bad args: $*" >&2; exit 90; }
env_file=$3
shift 4
echo "${env_file}" >"${FAKE_LOG}/env_file"
while IFS= read -r line; do
    case "${line#*=}" in
        op://*) export "${line%%=*}=fake-resolved-token" ;;
        *) export "${line?}" ;;
    esac
done <"${env_file}"
"$@"
STUB
    chmod +x "${dir}/op"
}

# A recording agent: writes its name, each argument on its own line, and the
# token it sees, then exits with FAKE_EXIT.
write_fake_agent() {
    local dir=$1 name=$2
    cat >"${dir}/${name}" <<STUB
#!/usr/bin/env bash
echo ${name} >"\${FAKE_LOG}/argv"
printf '%s\n' "\$@" >>"\${FAKE_LOG}/argv"
printf '%s\n' "\${GH_TOKEN:-}" >"\${FAKE_LOG}/token"
printf '%s\n' "\${GIT_AUTHOR_NAME:-}" >"\${FAKE_LOG}/author"
exit "\${FAKE_EXIT:-0}"
STUB
    chmod +x "${dir}/${name}"
}

# Runs the launcher with a fake bin dir first on PATH; prints its exit code.
run_launcher() {
    local bin=$1 log=$2 tmp=$3 code=$4
    shift 4
    local rc=0
    PATH="${bin}:/usr/bin:/bin" TMPDIR="${tmp}" FAKE_LOG="${log}" FAKE_EXIT="${code}" \
        TDS_BOT_GH_TOKEN_REF='op://vault/item/credential' \
        "$LAUNCHER" "$@" >/dev/null 2>"${log}/stderr" || rc=$?
    echo "${rc}"
}

expect_eq() {
    local name=$1 want=$2 got=$3
    if [ "${want}" = "${got}" ]; then pass=$((pass + 1)); else
        fail=$((fail + 1)); echo "FAIL: ${name}: want '${want}', got '${got}'" >&2
    fi
}

# --- Launch cases ---

launch_case() {
    local label=$1 agent=$2 code=$3
    local case_dir="${SCRATCH}/${label}"
    local bin="${case_dir}/bin" log="${case_dir}/log" tmp="${case_dir}/tmp"
    mkdir -p "${bin}" "${log}" "${tmp}"
    write_fake_op "${bin}"
    write_fake_agent "${bin}" claude
    if [ "${agent}" = clai ]; then
        write_fake_agent "${bin}" clai
    fi

    local rc
    rc=$(run_launcher "${bin}" "${log}" "${tmp}" "${code}" --model "two words" -p)

    expect_eq "${label}: launcher exits with the agent's status" "${code}" "${rc}"
    local want_argv
    if [ "${agent}" = clai ]; then
        want_argv=$(printf '%s\n' clai claude --model "two words" -p)
    else
        want_argv=$(printf '%s\n' claude --model "two words" -p)
    fi
    expect_eq "${label}: ${agent} runs with the arguments intact" "${want_argv}" "$(cat "${log}/argv" 2>/dev/null)"
    expect_eq "${label}: GH_TOKEN reaches the agent resolved" "fake-resolved-token" "$(cat "${log}/token" 2>/dev/null)"
    expect_eq "${label}: commits are the bot's" "9atatimer-bot" "$(cat "${log}/author" 2>/dev/null)"

    local env_file
    env_file=$(cat "${log}/env_file" 2>/dev/null)
    if [ -n "${env_file}" ] && [ ! -e "${env_file}" ]; then pass=$((pass + 1)); else
        fail=$((fail + 1)); echo "FAIL: ${label}: the env file '${env_file}' is left on disk" >&2
    fi
    refuse "${label}: no unbound-variable error" "$(cat "${log}/stderr")" 'unbound variable'
}

test_launch_runs_clai_and_cleans_up() {
    launch_case clai-ok clai 0
    launch_case clai-fails clai 7
}

test_launch_falls_back_to_claude() {
    launch_case claude-ok claude 0
    launch_case claude-fails claude 3
}

# --- Main ---

trap cleanup EXIT INT TERM HUP
SCRATCH=$(mktemp -d)

test_the_session_env_is_the_bot
test_no_reference_is_refused
test_a_literal_token_is_refused
test_launch_runs_clai_and_cleans_up
test_launch_falls_back_to_claude

echo "smoketest_claude_as_bot: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
