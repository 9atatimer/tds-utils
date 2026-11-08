#!/usr/bin/env bash
# smoketest_clai_omp_cf.sh -- clai.d/omp/pre/30-cf-workers-ai points omp at
# a Keychain key once one is seeded, so a launch never asks 1Password; it
# keeps the gateway routing from the file it wrote, and reads 1Password only
# on a new machine or a refresh. seed-gateway-key.zsh puts the key in the
# Keychain without it ever reaching argv.
#
# Hermetic: fake `op` (items and tags from fixtures, every call logged) and
# fake `security` (a directory as the keychain, every argv logged) go first
# on PATH, with a scratch HOME. No 1Password, no Keychain.
#
# Usage: ./test/smoketest_clai_omp_cf.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
HOOK="${REPO_DIR}/clai.d/omp/pre/30-cf-workers-ai"
SEED="${REPO_DIR}/clai.d/omp/seed-gateway-key.zsh"

KEYCHAIN_CMD="!security find-generic-password -s tds.omp.cf-gateway-key -a omp -w"
SECRET="sk-fake-gateway-key-123"

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
    # `read REF` prints FAKE_DIR/read/<REF with / as _>. Every call logged.
    cat >"${SCRATCH}/bin/op" <<'SH'
#!/usr/bin/env bash
echo "op $*" >>"${FAKE_DIR}/op.log"
case "$1 $2" in
    "item list") cat "${FAKE_DIR}/tag.$4" 2>/dev/null || echo '[]' ;;
    "read "*)
        ref="${*: -1}"
        f="${FAKE_DIR}/read/${ref//\//_}"
        [[ -e "$f" ]] || exit 1
        cat "$f"
        ;;
    *) exit 9 ;;
esac
SH

    # security: find-generic-password -s S -a A [-w] [kc]; -i reads one
    # add-generic-password line from stdin. Every argv logged.
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
[[ $1 == find-generic-password ]] || exit 9
shift
s="" a="" w=0
while (( $# )); do
    case $1 in -s) s=$2; shift ;; -a) a=$2; shift ;; -w) w=1 ;; esac
    shift
done
[[ -e "$kc/$s.$a" ]] || exit 44
(( w )) && cat "$kc/$s.$a"
exit 0
SH
    chmod +x "${SCRATCH}/bin/op" "${SCRATCH}/bin/security"
}

reset_state() {
    export FAKE_DIR="${SCRATCH}/state" HOME="${SCRATCH}/home"
    rm -rf "${FAKE_DIR}" "${HOME}"
    mkdir -p "${FAKE_DIR}/read" "${FAKE_DIR}/keychain" "${HOME}/.omp/agent"
    unset CLAI_OMP_REFRESH CLAI_OMP_CF_KEY_REF CLAI_OMP_CF_OP_ITEM
}

seed_keychain() { printf '%s' "${SECRET}" >"${FAKE_DIR}/keychain/tds.omp.cf-gateway-key.omp"; }

# One routing item tagged ai-gateway-routing, with its two fields.
routing_in_op() {
    echo '[{"id":"ritem","vault":{"id":"rvault"}}]' >"${FAKE_DIR}/tag.ai-gateway-routing"
    echo "https://gw.example/v1" >"${FAKE_DIR}/read/op:__rvault_ritem_gateway_base_url"
    echo "gw-id-1" >"${FAKE_DIR}/read/op:__rvault_ritem_gateway_gateway_id"
}

# A models.yml this hook wrote before, with the old `!op read` key.
old_owned_file() {
    cat >"${HOME}/.omp/agent/models.yml" <<'YML'
# managed by tds-utils clai.d/omp/pre/30-cf-workers-ai
providers:
  cf-workers-ai:
    baseUrl: https://gw.old/v1
    apiKey: "!op read 'op://v/i/credential'"
    headers:
      cf-aig-gateway-id: gw-old
YML
}

run_hook() { PATH="${SCRATCH}/bin:${PATH}" "${HOOK}" 2>"${FAKE_DIR}/stderr"; }

yml() { cat "${HOME}/.omp/agent/models.yml" 2>/dev/null; }
api_key() { awk '$1 == "apiKey:" { sub(/^ *apiKey: */, ""); print }' "${HOME}/.omp/agent/models.yml"; }
op_calls() { [[ -e "${FAKE_DIR}/op.log" ]] && wc -l <"${FAKE_DIR}/op.log" | tr -d ' ' || echo 0; }

# --- Hook tests ---

test_seeded_key_replaces_op_read_without_op() {
    reset_state
    old_owned_file
    seed_keychain
    run_hook || bad "hook exited non-zero"
    assert_eq "the key is read from the keychain" "\"${KEYCHAIN_CMD}\"" "$(api_key)"
    assert_eq "the routing is kept from the file" "https://gw.old/v1" "$(awk '$1 == "baseUrl:" {print $2}' <<<"$(yml)")"
    assert_eq "a launch with a seeded key calls op not at all" 0 "$(op_calls)"
    if grep -q "${SECRET}" <<<"$(yml)"; then bad "the key itself was written to models.yml"; else ok; fi
}

test_unchanged_run_writes_nothing() {
    reset_state
    old_owned_file
    seed_keychain
    run_hook
    : >"${FAKE_DIR}/stderr"
    run_hook
    if grep -q wrote "${FAKE_DIR}/stderr"; then bad "an unchanged file was rewritten"; else ok; fi
    assert_eq "an unchanged run calls op not at all" 0 "$(op_calls)"
}

test_new_machine_reads_routing_by_tag() {
    reset_state
    seed_keychain
    routing_in_op
    run_hook || bad "hook exited non-zero"
    assert_eq "routing base URL from the tagged item" "https://gw.example/v1" "$(awk '$1 == "baseUrl:" {print $2}' <<<"$(yml)")"
    assert_eq "routing gateway id from the tagged item" "gw-id-1" "$(awk '$1 == "cf-aig-gateway-id:" {print $2}' <<<"$(yml)")"
    if grep -q -- '--tags ai-gateway-routing' "${FAKE_DIR}/op.log"; then ok; else bad "routing not looked up by tag"; fi
}

test_no_key_writes_nothing_and_says_seed() {
    reset_state
    routing_in_op
    run_hook || bad "hook exited non-zero"
    assert_eq "no key: no file" "" "$(yml)"
    if grep -q 'seed-gateway-key.zsh' "${FAKE_DIR}/stderr"; then ok; else bad "no key: no seed hint"; fi
}

test_key_ref_is_the_unseeded_fallback() {
    reset_state
    routing_in_op
    export CLAI_OMP_CF_KEY_REF="op://v/k/credential"
    run_hook
    assert_eq "an unseeded key uses CLAI_OMP_CF_KEY_REF" "\"!op read 'op://v/k/credential'\"" "$(api_key)"
}

test_two_routing_items_write_nothing() {
    reset_state
    seed_keychain
    routing_in_op
    echo '[{"id":"a","vault":{"id":"v"}},{"id":"b","vault":{"id":"v"}}]' >"${FAKE_DIR}/tag.ai-gateway-routing"
    # Both items readable, so only the count check stops a write.
    local i
    for i in a b; do
        echo "https://gw.$i/v1" >"${FAKE_DIR}/read/op:__v_${i}_gateway_base_url"
        echo "gw-$i" >"${FAKE_DIR}/read/op:__v_${i}_gateway_gateway_id"
    done
    run_hook || bad "hook exited non-zero"
    assert_eq "two routing items: no file" "" "$(yml)"
}

test_hand_managed_file_is_left_alone() {
    reset_state
    seed_keychain
    echo "providers: {}  # mine" >"${HOME}/.omp/agent/models.yml"
    run_hook
    assert_eq "a file without the marker is left alone" "providers: {}  # mine" "$(yml)"
}

test_refresh_rereads_routing() {
    reset_state
    old_owned_file
    seed_keychain
    routing_in_op
    CLAI_OMP_REFRESH=1 run_hook
    assert_eq "a refresh reads the routing again" "https://gw.example/v1" "$(awk '$1 == "baseUrl:" {print $2}' <<<"$(yml)")"
}

# --- Seed tests ---

# Runs the seed script on a pseudo-terminal (it refuses without one).
run_seed() {
    PATH="${SCRATCH}/bin:${PATH}" CLAI_OMP_SEED_NO_HOOK=1 \
        python3 -c 'import pty, sys; sys.exit(pty.spawn(sys.argv[1:]) >> 8)' zsh -f "${SEED}" \
        >"${FAKE_DIR}/seed.out" 2>&1
}

test_seed_refuses_without_a_terminal() {
    reset_state
    local rc=0
    PATH="${SCRATCH}/bin:${PATH}" zsh -f "${SEED}" </dev/null >/dev/null 2>&1 || rc=$?
    if (( rc != 0 )); then ok; else bad "the seed ran without a terminal"; fi
}

test_seed_writes_the_tagged_key_off_argv() {
    reset_state
    echo '[{"id":"kitem","vault":{"id":"kvault"}}]' >"${FAKE_DIR}/tag.omp-ai-gateway-key"
    printf '%s' "${SECRET}" >"${FAKE_DIR}/read/op:__kvault_kitem_credential"
    run_seed || bad "seed exited non-zero: $(cat "${FAKE_DIR}/seed.out")"
    assert_eq "the tagged key is in the keychain" "${SECRET}" \
        "$(cat "${FAKE_DIR}/keychain/tds.omp.cf-gateway-key.omp" 2>/dev/null)"
    if grep -q "${SECRET}" "${FAKE_DIR}/security.argv"; then bad "the key reached security's argv"; else ok; fi
    if grep -q "${SECRET}" "${FAKE_DIR}/seed.out"; then bad "the key was printed"; else ok; fi
}

test_seed_refuses_two_tagged_keys() {
    reset_state
    echo '[{"id":"a","vault":{"id":"v"}},{"id":"b","vault":{"id":"v"}}]' >"${FAKE_DIR}/tag.omp-ai-gateway-key"
    if run_seed; then bad "the seed took one of two tagged keys"; else ok; fi
    assert_eq "two tagged keys: nothing written" "" "$(ls "${FAKE_DIR}/keychain")"
}

# --- Main ---

main() {
    command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not found"; exit 0; }
    make_fakes
    test_seeded_key_replaces_op_read_without_op
    test_unchanged_run_writes_nothing
    test_new_machine_reads_routing_by_tag
    test_no_key_writes_nothing_and_says_seed
    test_key_ref_is_the_unseeded_fallback
    test_two_routing_items_write_nothing
    test_hand_managed_file_is_left_alone
    test_refresh_rereads_routing
    if command -v zsh >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
        test_seed_refuses_without_a_terminal
        test_seed_writes_the_tagged_key_off_argv
        test_seed_refuses_two_tagged_keys
    else
        echo "SKIP: seed tests need zsh and python3"
    fi
    echo "smoketest_clai_omp_cf: ${pass} passed, ${fail} failed"
    (( fail == 0 ))
}

main "$@"
