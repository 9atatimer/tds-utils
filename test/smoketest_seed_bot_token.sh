#!/usr/bin/env bash
# smoketest_seed_bot_token.sh -- bin/seed-bot-token puts the bot's GitHub
# token in the Keychain from the one 1Password item tagged agents-gh-bot,
# never with the token in argv or output, and refuses anything else.
#
# Hermetic: fake `op` (items and values from fixtures) and fake `security`
# (a directory as the keychain, every argv logged) first on PATH. The
# script refuses without a terminal, so it runs on a pty from python3.
#
# Usage: ./test/smoketest_seed_bot_token.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
SEED="${REPO_DIR}/bin/seed-bot-token"
TOKEN="ghp_FakeBotToken123"

# --- Test harness ---

pass=0
fail=0

ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

assert_eq() {
    if [[ "$2" == "$3" ]]; then ok; else bad "$1: expected [$2], got [$3]"; fi
}

# --- Fixtures ---

SCRATCH=""

cleanup() {
    [[ -n ${SCRATCH} ]] && rm -rf "${SCRATCH}"
}

make_fakes() {
    SCRATCH="$(mktemp -d)"
    trap cleanup EXIT
    mkdir -p "${SCRATCH}/bin"

    # op: `item list --tags T --format json` prints FAKE_DIR/tag.<T>;
    # `read --no-newline REF` prints FAKE_DIR/read/<REF with / as _>.
    cat >"${SCRATCH}/bin/op" <<'SH'
#!/usr/bin/env bash
case "$1 $2" in
    "item list") cat "${FAKE_DIR}/tag.$4" 2>/dev/null || echo '[]' ;;
    "read --no-newline")
        f="${FAKE_DIR}/read/${3//\//_}"
        [[ -e "$f" ]] || exit 1
        cat "$f"
        ;;
    *) exit 9 ;;
esac
SH

    # security: -i reads one add-generic-password line from stdin;
    # find-generic-password -s S -a A succeeds when the item exists.
    cat >"${SCRATCH}/bin/security" <<'SH'
#!/usr/bin/env bash
echo "security $*" >>"${FAKE_DIR}/security.argv"
kc="${FAKE_DIR}/keychain"
if [[ $1 == -i ]]; then
    line=$(cat)
    s=$(sed -E 's/.* -s ([^ ]+) .*/\1/' <<<"$line")
    a=$(sed -E 's/.* -a ([^ ]+) .*/\1/' <<<"$line")
    w=$(sed -E 's/.* -w "([^"]*)".*/\1/' <<<"$line")
    printf '%s' "$w" >"$kc/$s.$a"
    exit 0
fi
[[ $1 == find-generic-password && $2 == -s && $4 == -a ]] || exit 9
[[ -e "$kc/$3.$5" ]]
SH
    chmod +x "${SCRATCH}/bin/op" "${SCRATCH}/bin/security"
}

reset_state() {
    export FAKE_DIR="${SCRATCH}/state"
    rm -rf "${FAKE_DIR}"
    mkdir -p "${FAKE_DIR}/read" "${FAKE_DIR}/keychain"
}

# One tagged item whose credential is $1.
tagged_item() {
    echo '[{"id":"item1","vault":{"id":"vault1"}}]' >"${FAKE_DIR}/tag.agents-gh-bot"
    printf '%s' "$1" >"${FAKE_DIR}/read/op:__vault1_item1_credential"
}

stored() { cat "${FAKE_DIR}/keychain/tds.github.9atatimer-bot.9atatimer-bot" 2>/dev/null; }

# Runs the seed on a pseudo-terminal; its output goes to $FAKE_DIR/out.
run_seed() {
    PATH="${SCRATCH}/bin:${PATH}" \
        python3 -c 'import pty, sys; sys.exit(pty.spawn(sys.argv[1:]) >> 8)' zsh -f "${SEED}" \
        >"${FAKE_DIR}/out" 2>&1
}

# --- Tests ---

test_refuses_without_a_terminal() {
    reset_state
    tagged_item "${TOKEN}"
    if PATH="${SCRATCH}/bin:${PATH}" zsh -f "${SEED}" </dev/null >/dev/null 2>&1; then
        bad "the seed ran without a terminal"
    else
        ok
    fi
    assert_eq "no terminal: nothing written" "" "$(stored)"
}

test_writes_the_tagged_token_off_argv() {
    reset_state
    tagged_item "${TOKEN}"
    run_seed || bad "seed exited non-zero: $(cat "${FAKE_DIR}/out")"
    assert_eq "the tagged token is in the keychain" "${TOKEN}" "$(stored)"
    if grep -q "${TOKEN}" "${FAKE_DIR}/security.argv"; then bad "the token reached security's argv"; else ok; fi
    if grep -q "${TOKEN}" "${FAKE_DIR}/out"; then bad "the token was printed"; else ok; fi
}

test_refuses_a_value_that_is_not_a_token() {
    reset_state
    tagged_item 'not a "token"'
    if run_seed; then bad "the seed stored a non-token"; else ok; fi
    assert_eq "non-token: nothing written" "" "$(stored)"
}

test_refuses_two_tagged_items() {
    reset_state
    echo '[{"id":"a","vault":{"id":"v"}},{"id":"b","vault":{"id":"v"}}]' >"${FAKE_DIR}/tag.agents-gh-bot"
    # Both readable, so only the count check stops a write.
    printf '%s' "${TOKEN}" >"${FAKE_DIR}/read/op:__v_a_credential"
    printf '%s' "${TOKEN}" >"${FAKE_DIR}/read/op:__v_b_credential"
    if run_seed; then bad "the seed took one of two tagged items"; else ok; fi
    assert_eq "two tagged items: nothing written" "" "$(stored)"
}

# --- Main ---

main() {
    for tool in jq zsh python3; do
        command -v "${tool}" >/dev/null 2>&1 || { echo "SKIP: ${tool} not found"; exit 0; }
    done
    make_fakes
    test_refuses_without_a_terminal
    test_writes_the_tagged_token_off_argv
    test_refuses_a_value_that_is_not_a_token
    test_refuses_two_tagged_items
    echo "smoketest_seed_bot_token: ${pass} passed, ${fail} failed"
    (( fail == 0 ))
}

main "$@"
