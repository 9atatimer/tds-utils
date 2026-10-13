#!/usr/bin/env bash
# smoketest_seed_ocr_review.sh -- behavioral smoke test for bin/seed-ocr-review
# (task-050; docs/design/OCR-ON-DEMAND.DESIGN.md, Seeder and G6).
#
# Hermetic: no network, no 1Password, no sleeps. `gh` and `op` are fakes on
# PATH backed by a fixture directory; every write the tool would make lands
# in a log the cases assert on, and the fake token must never appear in the
# tool's own output.
#
# Usage: ./test/smoketest_seed_ocr_review.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
TOOL="${REPO_DIR}/bin/seed-ocr-review"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

PIN_NEW="1111111111111111111111111111111111111111"
PIN_OLD="2222222222222222222222222222222222222222"
PIN_ZERO="0000000000000000000000000000000000000000"
ITEM="op://vault-uuid/item-title"
OPREF="op://vault-uuid/token-item/credential"
URL="https://gateway.example.invalid"

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

cleanup() { [ -n "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT INT TERM HUP

# --- Fixture ---------------------------------------------------------------
#
# ${FAKE_STATE}/owners/<owner>/type          User | Organization
# ${FAKE_STATE}/repos/<owner>/<repo>/        the repo exists
#   caller         .github/workflows/ocr-review-caller.yml (absent -> 404)
#   secret         repo secret updated_at (absent -> 404)
#   var.<NAME>     repo variable value (absent -> 404)
#   lastrun        "<conclusion> <createdAt>"
# ${FAKE_STATE}/org/<owner>/secret.repos      org secret's selected repos (absent -> 404)
# ${FAKE_STATE}/org/<owner>/var.<NAME>.repos  org variable's selected repos
# ${FAKE_STATE}/stale/<pin>                   compare <pin>...master touches ocr paths
# ${FAKE_STATE}/log                           every write and every op read

install_fakes() {
    local bin="${WORKROOT}/bin"
    mkdir -p "${bin}"
    cat > "${bin}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_STATE:?}"
args="$*"
repo_dir() { printf '%s/repos/%s\n' "${state}" "$1"; }
flag() { printf '%s' "${args}" | sed -n "s/.*$1 \([^ ]*\).*/\1/p"; }
case "${args}" in
    *"search/code"*)
        printf 'search %s\n' "${args}" >> "${state}/log"; exit 99 ;;
    "api users/"*)
        owner=$(printf '%s' "${args}" | sed -n 's|api users/\([^ ]*\).*|\1|p')
        cat "${state}/owners/${owner}/type" ;;
    "repo list"*)
        owner=$(printf '%s' "${args}" | awk '{print $3}')
        printf '%s\n' "${args}" >> "${state}/log"
        [ -e "${state}/list-fails" ] && { echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1; }
        for d in "${state}/repos/${owner}"/*/; do
            [ -d "${d}" ] || continue
            printf '%s/%s\n' "${owner}" "$(basename "${d}")"
        done ;;
    *"contents/.github/workflows/ocr-review-caller.yml"*)
        repo=$(printf '%s' "${args}" | sed -n 's|.*repos/\([^/]*/[^/]*\)/contents.*|\1|p')
        [ -e "$(repo_dir "${repo}")/caller-error" ] && { echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1; }
        f="$(repo_dir "${repo}")/caller"
        [ -f "${f}" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        base64 < "${f}" ;;
    *"tds-utils/compare/"*)
        pin=$(printf '%s' "${args}" | sed -n 's|.*compare/\([0-9a-f]*\)\.\.\..*|\1|p')
        if [ -e "${state}/stale/${pin}" ]; then echo 2; else echo 0; fi ;;
    "api repos/"*"/actions/secrets/"*)
        repo=$(printf '%s' "${args}" | sed -n 's|api repos/\([^/]*/[^/]*\)/actions.*|\1|p')
        f="$(repo_dir "${repo}")/secret"
        [ -f "${f}" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        cat "${f}" ;;
    "api orgs/"*"/actions/secrets/"*"/repositories"*)
        owner=$(printf '%s' "${args}" | sed -n 's|api orgs/\([^/]*\)/.*|\1|p')
        f="${state}/org/${owner}/secret.repos"
        [ -f "${f}" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        cat "${f}" ;;
    "api repos/"*"/actions/variables/"*)
        repo=$(printf '%s' "${args}" | sed -n 's|api repos/\([^/]*/[^/]*\)/actions.*|\1|p')
        name=$(printf '%s' "${args}" | sed -n 's|.*/actions/variables/\([A-Z_]*\).*|\1|p')
        f="$(repo_dir "${repo}")/var.${name}"
        [ -f "${f}" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        cat "${f}" ;;
    "api orgs/"*"/actions/variables/"*"/repositories"*)
        owner=$(printf '%s' "${args}" | sed -n 's|api orgs/\([^/]*\)/.*|\1|p')
        name=$(printf '%s' "${args}" | sed -n 's|.*/actions/variables/\([A-Z_]*\)/.*|\1|p')
        f="${state}/org/${owner}/var.${name}.repos"
        [ -f "${f}" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        cat "${f}" ;;
    "run list"*)
        repo=$(flag -R)
        f="$(repo_dir "${repo}")/lastrun"
        [ -f "${f}" ] && cat "${f}" || true ;;
    "secret set"*)
        name=$(printf '%s' "${args}" | awk '{print $3}')
        value=$(cat)
        if [ -n "$(flag --org)" ]; then
            printf 'org secret set %s %s repos=%s %s\n' "${name}" "$(flag --org)" "$(flag --repos)" "${value}" >> "${state}/log"
        else
            printf 'secret set %s %s %s\n' "${name}" "$(flag -R)" "${value}" >> "${state}/log"
        fi ;;
    "variable set"*)
        name=$(printf '%s' "${args}" | awk '{print $3}')
        if [ -n "$(flag --org)" ]; then
            printf 'org variable set %s %s repos=%s %s\n' "${name}" "$(flag --org)" "$(flag --repos)" "$(flag --body)" >> "${state}/log"
        else
            printf 'variable set %s %s %s\n' "${name}" "$(flag -R)" "$(flag --body)" >> "${state}/log"
        fi ;;
    *) echo "fake gh: unhandled: ${args}" >&2; exit 99 ;;
esac
EOF
    cat > "${bin}/op" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_STATE:?}"
[ "$1" = "read" ] || { echo "fake op: unhandled: $*" >&2; exit 99; }
printf 'op read %s\n' "$2" >> "${state}/log"
printf 'tok-for-%s\n' "$2"
EOF
    chmod +x "${bin}/gh" "${bin}/op"
}

caller_at() {
    printf 'jobs:\n  ocr-review:\n    uses: 9atatimer/tds-utils/.github/workflows/ocr-review.yml@%s\n    with:\n      tools_ref: %s\n' "$1" "$2"
}

# fixture <name> -- a fresh FAKE_STATE:
#   9atatimer (User):
#     alpha   caller at PIN_NEW, seeded, all three variables, last run green
#     beta    caller at the placeholder, unseeded, no variables
#     gamma   caller at PIN_OLD (stale), tools_ref mismatched
#     delta   no caller (not a consumer)
#   Nine-At-A-Time-Media (Organization):
#     tools   caller at PIN_NEW; org secret selected for ops only
#     ops     caller at PIN_NEW
fixture() {
    local name="$1"
    local state="${WORKROOT}/${name}"
    local u="${state}/repos/9atatimer" o="${state}/repos/Nine-At-A-Time-Media"
    mkdir -p "${state}/owners/9atatimer" "${state}/owners/Nine-At-A-Time-Media" "${state}/stale" \
        "${state}/org/Nine-At-A-Time-Media" "${u}/alpha" "${u}/beta" "${u}/gamma" "${u}/delta" "${o}/tools" "${o}/ops"
    echo User > "${state}/owners/9atatimer/type"
    echo Organization > "${state}/owners/Nine-At-A-Time-Media/type"
    caller_at "${PIN_NEW}" "${PIN_NEW}" > "${u}/alpha/caller"
    echo "2026-10-12T05:00:00Z" > "${u}/alpha/secret"
    echo "${ITEM}" > "${u}/alpha/var.OLLAMA_GATEWAY_OP_ITEM"
    echo "${URL}" > "${u}/alpha/var.OLLAMA_GATEWAY_URL"
    echo "qwen3.6:latest" > "${u}/alpha/var.OLLAMA_GATEWAY_MODEL"
    echo "success 2026-10-12T06:00:00Z" > "${u}/alpha/lastrun"
    caller_at "${PIN_ZERO}" "'${PIN_ZERO}'" > "${u}/beta/caller"
    caller_at "${PIN_OLD}" "${PIN_NEW}" > "${u}/gamma/caller"
    : > "${state}/stale/${PIN_OLD}"
    caller_at "${PIN_NEW}" "${PIN_NEW}" > "${o}/tools/caller"
    caller_at "${PIN_NEW}" "${PIN_NEW}" > "${o}/ops/caller"
    echo "Nine-At-A-Time-Media/ops" > "${state}/org/Nine-At-A-Time-Media/secret.repos"
    : > "${state}/log"
    printf '%s\n' "${state}"
}

# shellcheck disable=SC2034
run() {
    local state="$1"; shift
    RUN_RC=0
    RUN_OUT=$(FAKE_STATE="${state}" PATH="${WORKROOT}/bin:${PATH}" "${TOOL}" "$@" 2> "${state}/stderr") || RUN_RC=$?
    RUN_ERR=$(cat "${state}/stderr")
}

line_of() { printf '%s\n' "${RUN_OUT}" | grep -E "$1" || true; }

# --- Cases -----------------------------------------------------------------

case_status_user_owner() {
    bold "status (user owner): caller, pin and its state, secret, variables, last run"; echo
    local s; s=$(fixture status1)
    run "${s}" status
    assert "alpha: pinned at the new sha, current, seeded, 3/3 variables, last run success" \
        "line_of 9atatimer/alpha | grep -q '1111111' && line_of 9atatimer/alpha | grep -q 'current' && line_of 9atatimer/alpha | grep -q '2026-10-12T05' && line_of 9atatimer/alpha | grep -q '3/3' && line_of 9atatimer/alpha | grep -q success"
    assert "beta: the placeholder pin is called out" "line_of 9atatimer/beta | grep -q placeholder"
    assert "beta: unseeded and no variables" "line_of 9atatimer/beta | grep -q '0/3'"
    assert "gamma: a tools_ref that differs from the pin is called out" "line_of 9atatimer/gamma | grep -q mismatch"
    assert "delta: a repo with no caller is not listed" "! printf '%s' \"\${RUN_OUT}\" | grep -q delta"
    assert "status exits 1 while a consumer is not ready" "[ \"\${RUN_RC}\" -eq 1 ]"
    assert "discovery never used code search" "! grep -q '^search' '${s}/log'"
    assert "status wrote nothing and read no token" "! grep -q 'set\\|op read' '${s}/log'"
}

case_status_stale_pin() {
    bold "status: a pin behind master on the ocr-review files is stale"; echo
    local s; s=$(fixture stale1)
    caller_at "${PIN_OLD}" "${PIN_OLD}" > "${s}/repos/9atatimer/gamma/caller"
    run "${s}" status
    assert "gamma: stale" "line_of 9atatimer/gamma | grep -q stale"
}

case_status_org_owner() {
    bold "status (org owner): the org secret counts only for the repos it selects"; echo
    local s; s=$(fixture status2)
    run "${s}" -o Nine-At-A-Time-Media status
    assert "ops: org secret selected" "line_of Nine-At-A-Time-Media/ops | grep -q org"
    assert "tools: org secret not selected for it reads as unset" "! line_of Nine-At-A-Time-Media/tools | grep -q ' org '"
}

case_seed_user_owner() {
    bold "seed (user owner): secret from op read through a pipe, three variables per repo"; echo
    local s; s=$(fixture seed1)
    run "${s}" -i "${ITEM}" -r "${OPREF}" -u "${URL}" seed
    assert "seed exits 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "the token came from the -r op:// reference" "grep -q 'op read ${OPREF}' '${s}/log'"
    for r in alpha beta gamma; do
        assert "${r}: secret set from the pipe" "grep -q 'secret set OLLAMA_GATEWAY_OP_SA_TOKEN 9atatimer/${r} tok-for-' '${s}/log'"
        assert "${r}: OLLAMA_GATEWAY_OP_ITEM set" "grep -q 'variable set OLLAMA_GATEWAY_OP_ITEM 9atatimer/${r} ${ITEM}' '${s}/log'"
        assert "${r}: OLLAMA_GATEWAY_URL set" "grep -q 'variable set OLLAMA_GATEWAY_URL 9atatimer/${r} ${URL}' '${s}/log'"
        assert "${r}: OLLAMA_GATEWAY_MODEL set" "grep -q 'variable set OLLAMA_GATEWAY_MODEL 9atatimer/${r} qwen3.6:latest' '${s}/log'"
    done
    assert "delta (no caller) untouched" "! grep -q 'delta' '${s}/log'"
    assert "the token never appears in the tool's output" "! printf '%s%s' \"\${RUN_OUT}\" \"\${RUN_ERR}\" | grep -q 'tok-for'"
}

case_seed_org_owner() {
    bold "seed (org owner): one org secret and org variables, selecting every consumer, never dropping one"; echo
    local s; s=$(fixture seed2)
    echo "Nine-At-A-Time-Media/legacy" >> "${s}/org/Nine-At-A-Time-Media/secret.repos"
    run "${s}" -o Nine-At-A-Time-Media -i "${ITEM}" -r "${OPREF}" -u "${URL}" seed
    assert "seed exits 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "one org secret write" "[ \"\$(grep -c '^org secret set' '${s}/log')\" -eq 1 ]"
    assert "the org secret selects both consumers and keeps an existing selection" \
        "grep '^org secret set' '${s}/log' | grep -q 'Nine-At-A-Time-Media/ops' && grep '^org secret set' '${s}/log' | grep -q 'Nine-At-A-Time-Media/tools' && grep '^org secret set' '${s}/log' | grep -q 'Nine-At-A-Time-Media/legacy'"
    assert "three org variable writes, none per repo" "[ \"\$(grep -c '^org variable set' '${s}/log')\" -eq 3 ] && ! grep -q '^variable set' '${s}/log'"
    assert "no per-repo secret" "! grep -q '^secret set' '${s}/log'"
}

case_seed_named_repo() {
    bold "seed <repo>: only the named repo"; echo
    local s; s=$(fixture seed3)
    run "${s}" -i "${ITEM}" -r "${OPREF}" -u "${URL}" seed 9atatimer/delta
    assert "seed exits 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "delta seeded on request" "grep -q 'secret set OLLAMA_GATEWAY_OP_SA_TOKEN 9atatimer/delta' '${s}/log'"
    assert "nothing else seeded" "[ \"\$(grep -c '^secret set' '${s}/log')\" -eq 1 ]"
}

case_seed_needs_item() {
    bold "seed without the item reference refuses before reading or writing anything"; echo
    local s; s=$(fixture item1)
    run "${s}" seed
    assert "exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "says -i is needed" "printf '%s' \"\${RUN_ERR}\" | grep -q -- '-i'"
    assert "nothing read or written" "! grep -q 'set\\|op read' '${s}/log'"
}

case_seed_needs_token_ref_and_url() {
    bold "seed without -r or -u refuses before reading or writing anything: the public repo names no token item or gateway host"; echo
    local s; s=$(fixture ref1)
    run "${s}" -i "${ITEM}" -u "${URL}" seed
    assert "no -r: exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "no -r: says -r is needed" "printf '%s' \"\${RUN_ERR}\" | grep -q -- '-r'"
    assert "no -r: nothing read or written" "! grep -q 'set\\|op read' '${s}/log'"
    s=$(fixture url1)
    run "${s}" -i "${ITEM}" -r "${OPREF}" seed
    assert "no -u: exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "no -u: says -u is needed" "printf '%s' \"\${RUN_ERR}\" | grep -q -- '-u'"
    assert "no -u: nothing read or written" "! grep -q 'set\\|op read' '${s}/log'"
}

case_dry_run() {
    bold "-n seed: the plan, no token read, nothing set"; echo
    local s; s=$(fixture dry1)
    run "${s}" -n -i "${ITEM}" -r "${OPREF}" -u "${URL}" seed
    assert "dry run exits 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "no op read, no set" "! grep -q 'set\\|op read' '${s}/log'"
    assert "the plan names each consumer and each variable" \
        "printf '%s' \"\${RUN_OUT}\" | grep -q 'alpha' && printf '%s' \"\${RUN_OUT}\" | grep -q 'OLLAMA_GATEWAY_URL'"
}

case_discovery_failure() {
    bold "discovery failure: status and seed exit 2, nothing written"; echo
    local s; s=$(fixture disc1)
    : > "${s}/list-fails"
    run "${s}" status
    assert "status exits 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    run "${s}" -i "${ITEM}" -r "${OPREF}" -u "${URL}" seed
    assert "seed exits 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "nothing read or written" "! grep -q 'set\\|op read' '${s}/log'"
}

case_lookup_error() {
    bold "a caller lookup error is error, not absence"; echo
    local s; s=$(fixture look1)
    : > "${s}/repos/9atatimer/beta/caller-error"
    run "${s}" status
    assert "status exits 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "beta reads error" "line_of 9atatimer/beta | grep -q error"
    run "${s}" -i "${ITEM}" -r "${OPREF}" -u "${URL}" seed
    assert "seed refuses an incomplete target set" "[ \"\${RUN_RC}\" -eq 2 ] && ! grep -q 'set' '${s}/log'"
}

case_usage() {
    bold "usage: unknown or missing subcommand exits 2; -h exits 0"; echo
    local s; s=$(fixture usage1)
    run "${s}" frobnicate
    assert "unknown subcommand -> 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    run "${s}"
    assert "no subcommand -> 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    run "${s}" -h
    assert "-h -> 0 with usage" "[ \"\${RUN_RC}\" -eq 0 ] && printf '%s' \"\${RUN_OUT}\" | grep -qi usage"
}

# --- Main ------------------------------------------------------------------

main() {
    WORKROOT=$(mktemp -d)
    install_fakes
    case_status_user_owner
    case_status_stale_pin
    case_status_org_owner
    case_seed_user_owner
    case_seed_org_owner
    case_seed_named_repo
    case_seed_needs_item
    case_seed_needs_token_ref_and_url
    case_dry_run
    case_discovery_failure
    case_lookup_error
    case_usage
    echo
    printf 'ran %d, passed %d, failed %d\n' "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
