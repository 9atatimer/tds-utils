#!/usr/bin/env bash
# smoketest_seed_ci_magic.sh -- behavioral smoke test for bin/seed-ci-magic
# (issue #345).
#
# Hermetic: no network, no 1Password, no sleeps. `gh` and `op` are fakes on
# PATH backed by a fixture directory; every write the tool would make lands
# in a log the cases assert on, and the fake token must never appear in
# the tool's own output.
#
# Usage: ./test/smoketest_seed_ci_magic.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
TOOL="${REPO_DIR}/bin/seed-ci-magic"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

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
# ${FAKE_STATE}/repos/<owner>/<repo>/ holds per-repo facts; the directory
# itself is the repo's existence (`gh repo list <owner>` enumerates them):
#   workflow   the repo's .github/workflows/ci-magic.yml (absent -> 404)
#   secret     the secret's updated_at (absent -> 404)
#   lastrun    "<conclusion> <createdAt>" of the newest ci.magic run
# ${FAKE_STATE}/log records every write: "op read <ref>" and
# "secret set <name> <repo> <stdin>".

install_fakes() {
    local bin="${WORKROOT}/bin"
    mkdir -p "${bin}"
    cat > "${bin}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_STATE:?}"
args="$*"
repo_dir() { printf '%s/repos/%s\n' "${state}" "$1"; }
case "${args}" in
    *"search/code"*)
        # Code search is an eventually-consistent index, not an inventory
        # (tds-utils#348): the tool must not use it for discovery.
        printf 'search %s\n' "${args}" >> "${state}/log"
        echo "fake gh: code search must not be used for discovery" >&2; exit 99 ;;
    "repo list"*)
        # gh repo list <owner> ... -> every repo directory under the owner
        owner=$(printf '%s' "${args}" | awk '{print $3}')
        printf '%s\n' "${args}" >> "${state}/log"
        [ -e "${state}/list-fails" ] && { echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1; }
        for d in "${state}/repos/${owner}"/*/; do
            [ -d "${d}" ] || continue
            printf '%s/%s\n' "${owner}" "$(basename "${d}")"
        done ;;
    *"contents/.github/workflows/ci-magic.yml"*)
        repo=$(printf '%s' "${args}" | sed -n 's|.*repos/\([^/]*/[^/]*\)/contents.*|\1|p')
        f="$(repo_dir "${repo}")/workflow"
        [ -e "$(repo_dir "${repo}")/workflow-error" ] && { echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1; }
        [ -f "${f}" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        base64 < "${f}" ;;
    *"actions/secrets/"*)
        repo=$(printf '%s' "${args}" | sed -n 's|.*repos/\([^/]*/[^/]*\)/actions.*|\1|p')
        f="$(repo_dir "${repo}")/secret"
        [ -e "$(repo_dir "${repo}")/secret-error" ] && { echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1; }
        [ -f "${f}" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        cat "${f}" ;;
    "run list"*)
        repo=$(printf '%s' "${args}" | sed -n 's/.*-R \([^ ]*\).*/\1/p')
        f="$(repo_dir "${repo}")/lastrun"
        [ -f "${f}" ] && cat "${f}" || true ;;
    "secret set"*)
        name=$(printf '%s' "${args}" | awk '{print $3}')
        repo=$(printf '%s' "${args}" | sed -n 's/.*-R \([^ ]*\).*/\1/p')
        value=$(cat)
        mkdir -p "$(repo_dir "${repo}")"
        echo "2099-01-01T00:00:00Z" > "$(repo_dir "${repo}")/secret"
        printf 'secret set %s %s %s\n' "${name}" "${repo}" "${value}" >> "${state}/log" ;;
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

# fixture <name> -- a fresh FAKE_STATE with four 9atatimer repos:
#   jengris      real workflow on the mirror, seeded, last run green
#   sounddating  real workflow still on the org path, unseeded, last run red
#   Skills       no workflow (mentions ci-magic only in a comment), unseeded
#   iae          real workflow on the mirror, seeded -- the repo code search
#                dropped while reindexing (tds-utils#348)
fixture() {
    local name="$1"
    local state="${WORKROOT}/${name}"
    local r="${state}/repos/9atatimer"
    mkdir -p "${r}/jengris" "${r}/sounddating" "${r}/Skills" "${r}/iae"
    printf 'steps:\n  - uses: 9atatimer/ci-magic@main\n' > "${r}/iae/workflow"
    echo "2026-09-28T07:26:58Z" > "${r}/iae/secret"
    echo "success 2026-09-28T07:28:15Z" > "${r}/iae/lastrun"
    printf 'name: ci.magic\njobs:\n  ci-magic:\n    steps:\n      - uses: 9atatimer/ci-magic@main\n' > "${r}/jengris/workflow"
    echo "2026-09-28T05:10:00Z" > "${r}/jengris/secret"
    echo "success 2026-09-28T05:30:00Z" > "${r}/jengris/lastrun"
    printf 'name: ci.magic\njobs:\n  ci-magic:\n    steps:\n      - uses: Nine-At-A-Time-Media/template-tools/packages/naatm-ci-magic@main\n' > "${r}/sounddating/workflow"
    echo "failure 2026-09-18T20:48:00Z" > "${r}/sounddating/lastrun"
    : > "${state}/log"
    printf '%s\n' "${state}"
}

# run <state> <args...> -- run the tool against a fixture; captures stdout,
# stderr and exit code into RUN_OUT / RUN_ERR / RUN_RC (read by the assert
# conditions, which are eval'd strings -- hence the shellcheck waiver).
# shellcheck disable=SC2034
run() {
    local state="$1"; shift
    RUN_RC=0
    RUN_OUT=$(FAKE_STATE="${state}" PATH="${WORKROOT}/bin:${PATH}" "${TOOL}" "$@" 2> "${state}/stderr") || RUN_RC=$?
    RUN_ERR=$(cat "${state}/stderr")
}

# --- Cases -----------------------------------------------------------------

case_status_reports_each_repo() {
    bold "status: one line per discovered repo, with workflow, reference, secret, last run"; echo
    local s; s=$(fixture status1)
    run "${s}" status
    assert "jengris: workflow yes, mirror reference, seeded, last run success" \
        "printf '%s' \"\${RUN_OUT}\" | grep -E '9atatimer/jengris' | grep -q 'mirror' && printf '%s' \"\${RUN_OUT}\" | grep -E '9atatimer/jengris' | grep -q '2026-09-28T05:10' && printf '%s' \"\${RUN_OUT}\" | grep -E '9atatimer/jengris' | grep -q 'success'"
    assert "sounddating: org-path reference is called out as unresolvable" \
        "printf '%s' \"\${RUN_OUT}\" | grep -E '9atatimer/sounddating' | grep -q 'org-path'"
    assert "sounddating: missing secret shows as such" \
        "printf '%s' \"\${RUN_OUT}\" | grep -E '9atatimer/sounddating' | grep -q -- '-'"
    assert "Skills: a repo with no ci-magic.yml is not a consumer and is not listed" \
        "! printf '%s' \"\${RUN_OUT}\" | grep -q '9atatimer/Skills'"
    assert "iae: found by enumeration, not by search (tds-utils#348)" \
        "printf '%s' \"\${RUN_OUT}\" | grep -E '9atatimer/iae' | grep -q 'mirror'"
    assert "discovery never touched code search" "! grep -q '^search' '${s}/log'"
    assert "status exits 1 while a real consumer is misreferenced or unseeded" "[ \"\${RUN_RC}\" -eq 1 ]"
    assert "stderr carries only the not-ready summary (no base64/gh noise from the 404s)" \
        "[ \"\$(printf '%s\n' \"\${RUN_ERR}\" | grep -c .)\" -eq 1 ] && printf '%s' \"\${RUN_ERR}\" | grep -q 'not ready'"
}

case_status_exits_zero_when_every_consumer_is_ready() {
    bold "status: exit 0 once every real consumer is on the mirror and seeded"; echo
    local s; s=$(fixture status2)
    printf 'jobs:\n  x:\n    steps:\n      - uses: 9atatimer/ci-magic@v0\n' > "${s}/repos/9atatimer/sounddating/workflow"
    echo "2026-09-28T05:10:00Z" > "${s}/repos/9atatimer/sounddating/secret"
    run "${s}" status
    assert "all consumers ready -> exit 0 (Skills, with no workflow, does not count)" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "a pinned mirror ref (@v0) counts as the mirror" "printf '%s' \"\${RUN_OUT}\" | grep -E 'sounddating' | grep -q 'mirror'"
}

case_seed_seeds_real_consumers_only() {
    bold "seed: every repo with a real workflow gets the secret; comment-only matches do not"; echo
    local s; s=$(fixture seed1)
    run "${s}" seed
    assert "seed exits 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "jengris re-seeded (idempotent: already had one)" "grep -q 'secret set CI_MAGIC_OP_SA_TOKEN 9atatimer/jengris tok-for-' '${s}/log'"
    assert "sounddating seeded" "grep -q 'secret set CI_MAGIC_OP_SA_TOKEN 9atatimer/sounddating tok-for-' '${s}/log'"
    assert "Skills NOT seeded (no workflow)" "! grep -q '9atatimer/Skills' '${s}/log'"
    assert "the value came from the default op:// reference" "grep -q 'op read op://Development/btnk55jxtturjjmkyat5emf2wu/credential' '${s}/log'"
    assert "the token never appears in the tool's output" "! printf '%s%s' \"\${RUN_OUT}\" \"\${RUN_ERR}\" | grep -q 'tok-for'"
    assert "output names each seeded repo" "printf '%s' \"\${RUN_OUT}\" | grep -q 'jengris' && printf '%s' \"\${RUN_OUT}\" | grep -q 'sounddating'"
}

case_seed_named_repo() {
    bold "seed <repo>: an explicitly named repo is seeded even without a workflow"; echo
    local s; s=$(fixture seed2)
    run "${s}" seed 9atatimer/Skills
    assert "seed exits 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "Skills seeded on request" "grep -q 'secret set CI_MAGIC_OP_SA_TOKEN 9atatimer/Skills' '${s}/log'"
    assert "nothing else touched" "[ \"\$(grep -c 'secret set' '${s}/log')\" -eq 1 ]"
}

case_dry_run_touches_nothing() {
    bold "-n seed: the plan is printed, no token read, no secret set"; echo
    local s; s=$(fixture dry1)
    run "${s}" -n seed
    assert "dry run exits 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "no op read, no secret set" "! grep -q 'secret set\|op read' '${s}/log'"
    assert "the plan names the repos it would seed" "printf '%s' \"\${RUN_OUT}\" | grep -q 'jengris' && printf '%s' \"\${RUN_OUT}\" | grep -q 'sounddating'"
    assert "the plan does not include the comment-only match" "! printf '%s' \"\${RUN_OUT}\" | grep -q 'Skills'"
}

case_flags_override_defaults() {
    bold "-o / -s / -r: owner, secret name and op:// reference are flags"; echo
    local s; s=$(fixture flags1)
    mkdir -p "${s}/repos/other/app"; : > "${s}/repos/other/app/match"
    printf 'steps:\n  - uses: other/ci-magic@main\n' > "${s}/repos/other/app/workflow"
    run "${s}" -o other -s MY_SECRET -r op://v/i/f seed
    assert "seed exits 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "the other owner's repo was seeded under the given secret name" "grep -q 'secret set MY_SECRET other/app' '${s}/log'"
    assert "the value came from the given op:// reference" "grep -q 'op read op://v/i/f' '${s}/log'"
    assert "9atatimer repos were not touched" "! grep -q '9atatimer' '${s}/log'"
}

case_usage_on_bad_input() {
    bold "usage: an unknown subcommand and no subcommand both exit 2 with usage"; echo
    local s; s=$(fixture usage1)
    run "${s}" frobnicate
    assert "unknown subcommand -> exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "usage on stderr" "printf '%s' \"\${RUN_ERR}\" | grep -qi 'usage'"
    run "${s}"
    assert "no subcommand -> exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    run "${s}" -h
    assert "-h -> exit 0 with usage on stdout" "[ \"\${RUN_RC}\" -eq 0 ] && printf '%s' \"\${RUN_OUT}\" | grep -qi 'usage'"
}

# Codex review on PR #346: an API failure must never read as "ready" or
# as "not a consumer". Discovery failing, or a lookup failing for any
# reason other than 404, is exit 2 ("could not determine"), distinct
# from exit 1 ("determined: not ready").

case_discovery_failure_is_not_success() {
    bold "discovery failure: status and seed exit 2, nothing is seeded"; echo
    local s; s=$(fixture disc1)
    : > "${s}/list-fails"
    run "${s}" status
    assert "status exits 2 when the repository listing fails" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "the gh error reaches stderr" "printf '%s' \"\${RUN_ERR}\" | grep -q 'HTTP 403'"
    run "${s}" seed
    assert "seed exits 2 when the repository listing fails" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "seed set nothing and read no token" "! grep -q 'secret set\|op read' '${s}/log'"
}

case_lookup_error_is_not_absence() {
    bold "lookup error: a non-404 failure is reported as error, not as none/unseeded"; echo
    local s; s=$(fixture look1)
    : > "${s}/repos/9atatimer/sounddating/workflow-error"
    printf 'steps:\n  - uses: 9atatimer/ci-magic@main\n' > "${s}/repos/9atatimer/sounddating/workflow"
    echo "2026-09-28T05:10:00Z" > "${s}/repos/9atatimer/sounddating/secret"
    run "${s}" status
    assert "status exits 2 on a workflow lookup error" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "the repo's WORKFLOW column reads error, not none" "printf '%s' \"\${RUN_OUT}\" | grep -E 'sounddating' | grep -q 'error'"
    assert "jengris, unaffected, is still reported" "printf '%s' \"\${RUN_OUT}\" | grep -E 'jengris' | grep -q 'mirror'"
    run "${s}" seed
    assert "seed exits 2 rather than silently omitting the repo" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "seed set nothing (an incomplete target set is not acted on)" "! grep -q 'secret set' '${s}/log'"
    local t; t=$(fixture look2)
    : > "${t}/repos/9atatimer/jengris/secret-error"
    run "${t}" status
    assert "a secret lookup error also exits 2 and reads error" "[ \"\${RUN_RC}\" -eq 2 ] && printf '%s' \"\${RUN_OUT}\" | grep -E 'jengris' | grep -q 'error'"
}

# tds-utils#348: code search is an eventually-consistent index. It dropped
# iae minutes after iae's ci-magic.yml changed (total_count 4, items 3),
# so a search-based candidate set silently omits a real consumer. The
# candidate set is the owner's repository list, which is complete by
# construction; the fake gh refuses code search outright.
case_enumeration_is_authoritative() {
    bold "discovery enumerates the owner's repos; a consumer absent from code search is still found"; echo
    local s; s=$(fixture enum1)
    run "${s}" -n seed
    assert "the plan includes iae" "printf '%s' \"\${RUN_OUT}\" | grep -q '9atatimer/iae'"
    assert "the plan still excludes Skills (no workflow)" "! printf '%s' \"\${RUN_OUT}\" | grep -q 'Skills'"
    assert "discovery listed the owner's repositories" "grep -q '^repo list 9atatimer' '${s}/log'"
    assert "discovery asked for every repository, not the CLI's default 30" "grep -q '^repo list .*--limit' '${s}/log'"
    assert "code search was never called" "! grep -q '^search' '${s}/log'"
}

# --- Main ------------------------------------------------------------------

main() {
    WORKROOT=$(mktemp -d)
    install_fakes
    case_status_reports_each_repo
    case_status_exits_zero_when_every_consumer_is_ready
    case_seed_seeds_real_consumers_only
    case_seed_named_repo
    case_dry_run_touches_nothing
    case_flags_override_defaults
    case_usage_on_bad_input
    case_discovery_failure_is_not_success
    case_lookup_error_is_not_absence
    case_enumeration_is_authoritative
    echo
    printf 'ran %d, passed %d, failed %d\n' "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
