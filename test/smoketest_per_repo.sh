#!/usr/bin/env bash
# smoketest_per_repo.sh -- behavioral smoke test for bin/per-repo and its
# first action, bin/per-repo-ci-runs-on.
#
# Hermetic: no network, no sleeps. `gh` is a fake on PATH backed by a
# fixture directory; every write lands in a log the cases assert on. The
# per-repo cases drive a recording fake action, so they test the runner's
# contract (discovery, the select pass, the environment it hands an action,
# exit codes) and nothing about any one action.
#
# Usage: ./test/smoketest_per_repo.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
TOOL="${REPO_DIR}/bin/per-repo"

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
#   visibility        private (default) or public
#   branch            default branch (default main)
#   workflows/<f>     files under .github/workflows (none -> 404)
#   workflows-error   the workflows listing fails for a reason other than 404
#   variable          the CI_RUNS_ON value (absent -> not found)
# ${FAKE_STATE}/list-fails makes discovery fail.
# ${FAKE_STATE}/log records discovery and every write.

install_fakes() {
    local bin="${WORKROOT}/bin"
    mkdir -p "${bin}"
    cat > "${bin}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_STATE:?}"
args="$*"
repo_dir() { printf '%s/repos/%s\n' "${state}" "$1"; }
flag_r() { printf '%s' "${args}" | sed -n 's/.*-R \([^ ]*\).*/\1/p'; }
case "${args}" in
    *"search/code"*)
        printf 'search %s\n' "${args}" >> "${state}/log"
        echo "fake gh: code search must not be used for discovery" >&2; exit 99 ;;
    "repo list"*)
        owner=$(printf '%s' "${args}" | awk '{print $3}')
        printf 'list %s\n' "${owner}" >> "${state}/log"
        [ -e "${state}/list-fails" ] && { echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1; }
        for d in "${state}/repos/${owner}"/*/; do
            [ -d "${d}" ] || continue
            vis=private; [ -f "${d}visibility" ] && vis=$(cat "${d}visibility")
            br=main; [ -f "${d}branch" ] && br=$(cat "${d}branch")
            printf '%s/%s\t%s\t%s\n' "${owner}" "$(basename "${d}")" "${vis}" "${br}"
        done ;;
    "repo view"*)
        repo=$(printf '%s' "${args}" | awk '{print $3}')
        d="$(repo_dir "${repo}")"
        [ -d "${d}" ] || { echo "gh: Could not resolve to a Repository (HTTP 404)" >&2; exit 1; }
        vis=private; [ -f "${d}/visibility" ] && vis=$(cat "${d}/visibility")
        br=main; [ -f "${d}/branch" ] && br=$(cat "${d}/branch")
        printf '%s\t%s\t%s\n' "${repo}" "${vis}" "${br}" ;;
    *"contents/.github/workflows/"*)
        repo=$(printf '%s' "${args}" | sed -n 's|.*repos/\([^/]*/[^/]*\)/contents.*|\1|p')
        name=$(printf '%s' "${args}" | sed -n 's|.*contents/.github/workflows/\([^ ]*\).*|\1|p')
        f="$(repo_dir "${repo}")/workflows/${name}"
        [ -e "${f}.error" ] && { echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1; }
        [ -f "${f}" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        base64 < "${f}" ;;
    *"contents/.github/workflows"*)
        repo=$(printf '%s' "${args}" | sed -n 's|.*repos/\([^/]*/[^/]*\)/contents.*|\1|p')
        d="$(repo_dir "${repo}")"
        [ -e "${d}/workflows-error" ] && { echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1; }
        [ -d "${d}/workflows" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
        for f in "${d}/workflows"/*; do [ -f "${f}" ] && basename "${f}"; done ;;
    "variable get"*)
        f="$(repo_dir "$(flag_r)")/variable"
        [ -f "${f}" ] || { echo "variable CI_RUNS_ON was not found" >&2; exit 1; }
        cat "${f}" ;;
    "variable set"*)
        repo=$(flag_r)
        value=$(printf '%s' "${args}" | sed -n 's/.*--body \(.*\)$/\1/p')
        printf '%s\n' "${value}" > "$(repo_dir "${repo}")/variable"
        printf 'variable set %s %s %s\n' "$(printf '%s' "${args}" | awk '{print $3}')" "${repo}" "${value}" >> "${state}/log" ;;
    "variable delete"*)
        repo=$(flag_r)
        rm -f "$(repo_dir "${repo}")/variable"
        printf 'variable delete %s %s\n' "$(printf '%s' "${args}" | awk '{print $3}')" "${repo}" >> "${state}/log" ;;
    *) echo "fake gh: unhandled: ${args}" >&2; exit 99 ;;
esac
EOF
    # A recording action for the runner's own cases. In select mode it
    # answers from ${FAKE_STATE}/select/<repo-name> (missing -> applies);
    # in run mode it exits with ${FAKE_STATE}/run-rc/<repo-name> (missing -> 0).
    cat > "${bin}/per-repo-record" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_STATE:?}"
printf '%s %s owner=%s name=%s vis=%s branch=%s dry=%s args=%s\n' \
    "${PER_REPO_MODE}" "${PER_REPO}" "${PER_REPO_OWNER}" "${PER_REPO_NAME}" \
    "${PER_REPO_VISIBILITY}" "${PER_REPO_DEFAULT_BRANCH}" "${PER_REPO_DRY_RUN}" "$*" >> "${state}/calls"
if [ "${PER_REPO_MODE}" = select ]; then
    f="${state}/select/${PER_REPO_NAME}"
    [ -f "${f}" ] && exit "$(cat "${f}")"
    exit 0
fi
echo "ran ${PER_REPO}"
f="${state}/run-rc/${PER_REPO_NAME}"
[ -f "${f}" ] && exit "$(cat "${f}")"
exit 0
EOF
    chmod +x "${bin}/gh" "${bin}/per-repo-record"
}

# fixture <name> -- a fresh FAKE_STATE with four 9atatimer repos:
#   iae        private; a workflow reads vars.CI_RUNS_ON; variable set
#   grubsta    private; a workflow reads vars.CI_RUNS_ON; variable unset
#   jengris    private; workflows that do not read it
#   pubthing   public;  a workflow reads it (must never get the variable)
# The workflow bodies carry GitHub's literal ${{ ... }}: single quotes on purpose.
# shellcheck disable=SC2016
fixture() {
    local name="$1"
    local state="${WORKROOT}/${name}"
    local r="${state}/repos/9atatimer"
    mkdir -p "${r}/iae/workflows" "${r}/grubsta/workflows" "${r}/jengris/workflows" "${r}/pubthing/workflows" \
        "${state}/select" "${state}/run-rc"
    printf 'jobs:\n  t:\n    runs-on: ${{ fromJSON(vars.CI_RUNS_ON || %s) }}\n' "'\"ubuntu-latest\"'" > "${r}/iae/workflows/gate.yml"
    printf 'jobs:\n  t:\n    runs-on: ubuntu-latest\n' > "${r}/iae/workflows/deploy.yml"
    printf '["self-hosted","linux","x64","cf-pool"]\n' > "${r}/iae/variable"
    printf 'jobs:\n  t:\n    runs-on: ${{ fromJSON(vars.CI_RUNS_ON || %s) }}\n' "'\"ubuntu-latest\"'" > "${r}/grubsta/workflows/ci.yaml"
    printf 'jobs:\n  t:\n    runs-on: ubuntu-latest\n' > "${r}/jengris/workflows/gate.yml"
    printf 'jobs:\n  t:\n    runs-on: ${{ fromJSON(vars.CI_RUNS_ON || %s) }}\n' "'\"ubuntu-latest\"'" > "${r}/pubthing/workflows/gate.yml"
    echo public > "${r}/pubthing/visibility"
    echo master > "${r}/jengris/branch"
    : > "${state}/log"; : > "${state}/calls"
    printf '%s\n' "${state}"
}

# run <state> <args...> -- run per-repo against a fixture; captures stdout,
# stderr and exit code into RUN_OUT / RUN_ERR / RUN_RC (read by the assert
# conditions, which are eval'd strings -- hence the shellcheck waiver).
# shellcheck disable=SC2034
run() {
    local state="$1"; shift
    RUN_RC=0
    RUN_OUT=$(FAKE_STATE="${state}" PATH="${WORKROOT}/bin:${REPO_DIR}/bin:${PATH}" "${TOOL}" "$@" 2> "${state}/stderr") || RUN_RC=$?
    RUN_ERR=$(cat "${state}/stderr")
}

calls() { grep -c "^$2 " "$1/calls" || true; }

# --- Cases: the runner -----------------------------------------------------

case_runs_the_action_on_every_selected_repo_with_its_environment() {
    bold "per-repo: selects every repo, then runs the action on each with its facts in the environment"; echo
    local s; s=$(fixture runner1)
    run "${s}" -o 9atatimer record status
    assert "exit 0 when every run succeeds" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "select is asked of all four repos" "[ \"\$(calls '${s}' select)\" -eq 4 ]"
    assert "run is called on all four" "[ \"\$(calls '${s}' run)\" -eq 4 ]"
    assert "the environment names owner, repo, visibility and default branch" \
        "grep -q '^run 9atatimer/jengris owner=9atatimer name=jengris vis=private branch=master dry=0 args=status$' '${s}/calls'"
    assert "the action's output passes through" "printf '%s' \"\${RUN_OUT}\" | grep -q 'ran 9atatimer/iae'"
    assert "discovery listed the owner and never used code search" \
        "grep -q '^list 9atatimer$' '${s}/log' && ! grep -q '^search' '${s}/log'"
}

case_a_repo_the_action_declines_is_never_run() {
    bold "per-repo: a select answer of 10 (not applicable) skips the repo"; echo
    local s; s=$(fixture runner2)
    echo 10 > "${s}/select/jengris"
    run "${s}" -o 9atatimer record status
    assert "exit 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "jengris is not run" "! grep -q '^run 9atatimer/jengris' '${s}/calls'"
    assert "the other three are" "[ \"\$(calls '${s}' run)\" -eq 3 ]"
}

case_an_undecidable_repo_aborts_before_anything_runs() {
    bold "per-repo: a select error (2) on any repo aborts the whole run before any action runs"; echo
    local s; s=$(fixture runner3)
    echo 2 > "${s}/select/grubsta"
    run "${s}" -o 9atatimer record set
    assert "exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "no repo is run" "[ \"\$(calls '${s}' run)\" -eq 0 ]"
    assert "stderr says the target set could not be determined" "printf '%s' \"\${RUN_ERR}\" | grep -q 'could not determine'"
}

case_a_failed_discovery_runs_nothing() {
    bold "per-repo: when the repo listing fails, nothing is selected or run"; echo
    local s; s=$(fixture runner4)
    touch "${s}/list-fails"
    run "${s}" -o 9atatimer record status
    assert "exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "the action is never called" "[ ! -s '${s}/calls' ]"
    assert "stderr names the owner it could not list" "printf '%s' \"\${RUN_ERR}\" | grep -q '9atatimer'"
}

case_visibility_filter() {
    bold "per-repo: -v private leaves public repos out before the action sees them"; echo
    local s; s=$(fixture runner5)
    run "${s}" -o 9atatimer -v private record status
    assert "pubthing is neither selected nor run" "! grep -q 'pubthing' '${s}/calls'"
    assert "the three private repos are run" "[ \"\$(calls '${s}' run)\" -eq 3 ]"
}

case_named_repos_skip_discovery_and_select() {
    bold "per-repo: repos named after -- are run directly, with no listing and no select pass"; echo
    local s; s=$(fixture runner6)
    run "${s}" -o 9atatimer record status -- 9atatimer/iae
    assert "exit 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "only iae is run" "[ \"\$(calls '${s}' run)\" -eq 1 ] && grep -q '^run 9atatimer/iae ' '${s}/calls'"
    assert "no select pass" "[ \"\$(calls '${s}' select)\" -eq 0 ]"
}

case_exit_code_aggregates_the_runs() {
    bold "per-repo: a run that reports not-ready (1) makes the whole run exit 1; an error (2) wins over it"; echo
    local s; s=$(fixture runner7)
    echo 1 > "${s}/run-rc/grubsta"
    run "${s}" -o 9atatimer record status
    assert "one not-ready -> exit 1, and every repo still ran" \
        "[ \"\${RUN_RC}\" -eq 1 ] && [ \"\$(calls '${s}' run)\" -eq 4 ]"
    echo 2 > "${s}/run-rc/iae"; : > "${s}/calls"
    run "${s}" -o 9atatimer record status
    assert "an error and a not-ready -> exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
}

case_dry_run_reaches_the_action() {
    bold "per-repo: -n is handed to the action as PER_REPO_DRY_RUN=1"; echo
    local s; s=$(fixture runner8)
    run "${s}" -o 9atatimer -n record set
    assert "every run carries dry=1" "[ \"\$(grep -c '^run .* dry=1 ' '${s}/calls')\" -eq 4 ]"
}

case_unknown_action_is_a_usage_error() {
    bold "per-repo: an action that resolves to nothing is refused before discovery"; echo
    local s; s=$(fixture runner9)
    run "${s}" -o 9atatimer no-such-action status
    assert "exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "nothing was listed" "! grep -q '^list' '${s}/log'"
    assert "stderr names the action" "printf '%s' \"\${RUN_ERR}\" | grep -q 'no-such-action'"
}

# --- Cases: the ci-runs-on action ------------------------------------------

case_ci_runs_on_status() {
    bold "ci-runs-on status: private repos whose workflows read vars.CI_RUNS_ON, with the variable's value"; echo
    local s; s=$(fixture cro1)
    run "${s}" -o 9atatimer ci-runs-on status
    assert "iae is listed with its value" \
        "printf '%s' \"\${RUN_OUT}\" | grep '9atatimer/iae' | grep -q 'cf-pool'"
    assert "iae names the workflow that reads it, not the one that does not" \
        "printf '%s' \"\${RUN_OUT}\" | grep '9atatimer/iae' | grep -q 'gate.yml' && ! printf '%s' \"\${RUN_OUT}\" | grep '9atatimer/iae' | grep -q 'deploy.yml'"
    assert "grubsta (a .yaml workflow) is listed as unset" \
        "printf '%s' \"\${RUN_OUT}\" | grep '9atatimer/grubsta' | grep -q -- ' - '"
    assert "jengris (no workflow reads it) is not listed" "! printf '%s' \"\${RUN_OUT}\" | grep -q jengris"
    assert "pubthing (public) is not listed" "! printf '%s' \"\${RUN_OUT}\" | grep -q pubthing"
    assert "status exits 1 while a reader has no variable" "[ \"\${RUN_RC}\" -eq 1 ]"
    assert "status wrote nothing" "! grep -q '^variable' '${s}/log'"
}

case_ci_runs_on_set() {
    bold "ci-runs-on set: sets the pool labels on every private reader, and only there"; echo
    local s; s=$(fixture cro2)
    run "${s}" -o 9atatimer ci-runs-on set
    assert "exit 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "grubsta gets the default pool labels" \
        "grep -q '^variable set CI_RUNS_ON 9atatimer/grubsta \[\"self-hosted\",\"linux\",\"x64\",\"cf-pool\"\]$' '${s}/log'"
    assert "jengris and pubthing are untouched" "! grep -q -E 'jengris|pubthing' '${s}/log'"
    run "${s}" -o 9atatimer ci-runs-on status
    assert "status is green afterwards" "[ \"\${RUN_RC}\" -eq 0 ]"
}

# shellcheck disable=SC2034  # RUN_OUT/RUN_RC are read by the eval'd assert conditions
case_ci_runs_on_dry_run_and_labels() {
    bold "ci-runs-on: -n prints the plan and writes nothing; CI_RUNS_ON_LABELS overrides the value"; echo
    local s; s=$(fixture cro3)
    run "${s}" -o 9atatimer -n ci-runs-on set
    assert "dry run names grubsta" "printf '%s' \"\${RUN_OUT}\" | grep -q 'would set CI_RUNS_ON on 9atatimer/grubsta'"
    assert "dry run wrote nothing" "! grep -q '^variable' '${s}/log'"
    RUN_RC=0
    RUN_OUT=$(FAKE_STATE="${s}" CI_RUNS_ON_LABELS='["self-hosted","cf-big"]' PATH="${WORKROOT}/bin:${REPO_DIR}/bin:${PATH}" "${TOOL}" -o 9atatimer ci-runs-on set -- 9atatimer/grubsta 2>/dev/null) || RUN_RC=$?
    assert "the override value is what gets set" \
        "grep -q '^variable set CI_RUNS_ON 9atatimer/grubsta \[\"self-hosted\",\"cf-big\"\]$' '${s}/log'"
}

case_ci_runs_on_unset() {
    bold "ci-runs-on unset: removes the variable, which is the rollback"; echo
    local s; s=$(fixture cro4)
    run "${s}" -o 9atatimer ci-runs-on unset -- 9atatimer/iae
    assert "exit 0" "[ \"\${RUN_RC}\" -eq 0 ]"
    assert "iae's variable was deleted" "grep -q '^variable delete CI_RUNS_ON 9atatimer/iae$' '${s}/log'"
}

case_ci_runs_on_refuses_a_public_repo_even_when_named() {
    bold "ci-runs-on set: a public repo named directly is refused (its pool jobs would queue forever)"; echo
    local s; s=$(fixture cro5)
    run "${s}" -o 9atatimer ci-runs-on set -- 9atatimer/pubthing
    assert "exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "nothing written" "! grep -q '^variable' '${s}/log'"
}

case_ci_runs_on_lookup_failure_aborts() {
    bold "ci-runs-on: a workflows listing that fails (not 404) aborts the run before any write"; echo
    local s; s=$(fixture cro6)
    touch "${s}/repos/9atatimer/jengris/workflows-error"
    run "${s}" -o 9atatimer ci-runs-on set
    assert "exit 2" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "nothing written" "! grep -q '^variable' '${s}/log'"
}

case_ci_runs_on_workflow_fetch_failure_aborts() {
    bold "ci-runs-on: one workflow file that fails to fetch (not 404) aborts the run before any write"; echo
    local s; s=$(fixture cro7)
    touch "${s}/repos/9atatimer/grubsta/workflows/ci.yaml.error"
    run "${s}" -o 9atatimer ci-runs-on set
    assert "exit 2, not a silent skip" "[ \"\${RUN_RC}\" -eq 2 ]"
    assert "nothing written" "! grep -q '^variable' '${s}/log'"
}

# --- Main ------------------------------------------------------------------

main() {
    WORKROOT=$(mktemp -d)
    install_fakes
    case_runs_the_action_on_every_selected_repo_with_its_environment
    case_a_repo_the_action_declines_is_never_run
    case_an_undecidable_repo_aborts_before_anything_runs
    case_a_failed_discovery_runs_nothing
    case_visibility_filter
    case_named_repos_skip_discovery_and_select
    case_exit_code_aggregates_the_runs
    case_dry_run_reaches_the_action
    case_unknown_action_is_a_usage_error
    case_ci_runs_on_status
    case_ci_runs_on_set
    case_ci_runs_on_dry_run_and_labels
    case_ci_runs_on_unset
    case_ci_runs_on_refuses_a_public_repo_even_when_named
    case_ci_runs_on_lookup_failure_aborts
    case_ci_runs_on_workflow_fetch_failure_aborts
    echo
    printf '%s run, ' "${TESTS_RUN}"; green "${TESTS_PASSED} passed"; printf ', '
    if [ "${TESTS_FAILED}" -gt 0 ]; then red "${TESTS_FAILED} failed"; echo; exit 1; fi
    echo "0 failed"
}

main "$@"
