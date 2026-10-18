#!/usr/bin/env bash
# smoketest_changed_scopes.sh -- behaviours of .github/scripts/changed-scopes.sh,
# the classifier that decides which dist-ci jobs a change runs.
#
# A wrong rule here skips a suite and leaves `gate` green having tested
# nothing, so dist-ci's `changes` job runs this before it classifies.
#
# Hermetic: throwaway git repos under a temp dir; no network.
#
# Usage: ./test/smoketest_changed_scopes.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
CLASSIFIER="${REPO_DIR}/.github/scripts/changed-scopes.sh"

ALL_TRUE="smoketests=true shellcheck=true chores=true dynomark-contract=true dynomark-daemon=true dynomark-extension=true dynomark-e2e=true"

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }

assert_eq() {
    local label="$1" want="$2" got="$3"
    TESTS_RUN=$((TESTS_RUN + 1))
    if [ "${want}" = "${got}" ]; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n    want: %s\n    got:  %s\n' "${label}" "${want}" "${got}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT INT TERM HUP

# --- Helpers ---

# classify <dir> <file>... -- the classifier's outputs, one line, run from
# <dir> so shebang detection reads that tree.
classify() {
    local dir="$1"
    shift
    (cd "${dir}" && printf '%s\n' "$@" | GITHUB_OUTPUT='' bash "${CLASSIFIER}" classify) | tr '\n' ' ' | sed 's/ $//'
}

# only <scope>... -- the expected output line with just those scopes true.
only() {
    local scope out="" want
    for scope in smoketests shellcheck chores dynomark-contract dynomark-daemon dynomark-extension dynomark-e2e; do
        want=false
        case " $* " in *" ${scope} "*) want=true ;; esac
        out="${out}${scope}=${want} "
    done
    echo "${out% }"
}

# --- Cases ---

test_inert() {
    local d="${WORKROOT}/empty"
    mkdir -p "${d}"
    printf 'Docs-only changes run nothing\n'
    assert_eq "TODO_PLAN.md + docs/**/*.md (tds-utils PR#560)" "$(only)" \
        "$(classify "${d}" TODO_PLAN.md docs/arch/ocr-review/ARCHITECTURE.md docs/design/OCR-ON-DEMAND.DESIGN.md)"
    assert_eq "tasks/*.md and .github/*.md" "$(only)" \
        "$(classify "${d}" tasks/task-001.md .github/copilot-instructions.md)"
    assert_eq "docs/**/*.html diagram" "$(only)" "$(classify "${d}" docs/arch/ocr-review/ocr-review.html)"
    assert_eq "empty diff" "$(only)" "$(classify "${d}")"
}

test_catch_all() {
    local d="${WORKROOT}/empty"
    printf 'Anything else runs smoketests and shellcheck\n'
    assert_eq "bin/ script" "$(only smoketests shellcheck)" "$(classify "${d}" bin/tds-status)"
    assert_eq "docs/*.yml a node suite reads" "$(only smoketests shellcheck)" \
        "$(classify "${d}" docs/ocr-review-caller.yml)"
    assert_eq "another workflow file" "$(only smoketests shellcheck)" \
        "$(classify "${d}" .github/workflows/ocr-review.yml)"
    assert_eq "docs/ css beside a diagram" "$(only smoketests shellcheck)" "$(classify "${d}" docs/arch/x.css)"
}

test_trees() {
    local d="${WORKROOT}/empty"
    printf 'dynomark/ and chores/ run their own jobs, Markdown included\n'
    assert_eq "contract change runs every dynomark job" \
        "$(only dynomark-contract dynomark-daemon dynomark-extension dynomark-e2e)" \
        "$(classify "${d}" dynomark/contract/README.md)"
    assert_eq "daemon -> daemon + e2e" "$(only dynomark-daemon dynomark-e2e)" \
        "$(classify "${d}" dynomark/daemon/src/x.py)"
    assert_eq "extension -> extension + e2e" "$(only dynomark-extension dynomark-e2e)" \
        "$(classify "${d}" dynomark/extension/src/x.ts)"
    assert_eq "e2e -> e2e" "$(only dynomark-e2e)" "$(classify "${d}" dynomark/e2e/x.spec.ts)"
    assert_eq "dynomark/README.md runs every dynomark job" \
        "$(only dynomark-contract dynomark-daemon dynomark-extension dynomark-e2e)" \
        "$(classify "${d}" dynomark/README.md)"
    assert_eq "chores/ Markdown runs chores" "$(only chores)" "$(classify "${d}" chores/README.md)"
    assert_eq "chores/ .sh also runs smoketests (syntax sweep)" "$(only smoketests chores)" \
        "$(classify "${d}" chores/verify.sh)"
}

test_shebang() {
    local d="${WORKROOT}/shebang"
    mkdir -p "${d}/dynomark/daemon" "${d}/chores"
    printf '#!/usr/bin/env zsh\necho hi\n' >"${d}/dynomark/daemon/run"
    printf '#!/bin/bash\necho hi\n' >"${d}/chores/hook"
    printf 'Shell by shebang runs smoketests\n'
    assert_eq "extensionless zsh in dynomark/daemon" \
        "$(only smoketests dynomark-daemon dynomark-e2e)" "$(classify "${d}" dynomark/daemon/run)"
    assert_eq "extensionless bash in chores" "$(only smoketests chores)" "$(classify "${d}" chores/hook)"
}

test_gate_files() {
    local d="${WORKROOT}/empty" f
    printf 'A gate file runs everything\n'
    for f in .github/workflows/dist-ci.yml .github/scripts/changed-scopes.sh test/smoketest_changed_scopes.sh; do
        assert_eq "${f}" "${ALL_TRUE}" "$(classify "${d}" README.md "${f}")"
    done
}

test_union() {
    local d="${WORKROOT}/empty"
    printf 'Scopes union across files\n'
    assert_eq "docs + chores + extension" "$(only chores dynomark-extension dynomark-e2e)" \
        "$(classify "${d}" docs/a.md chores/src/x.py dynomark/extension/a.ts)"
}

make_pr_repo() {
    local d="$1" merge="$2"
    git init -q -b master "${d}"
    git -C "${d}" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base
    git -C "${d}" checkout -q -b topic
    mkdir -p "${d}/docs"
    printf 'x\n' >"${d}/docs/a.md"
    git -C "${d}" add docs/a.md
    git -C "${d}" -c user.email=t@t -c user.name=t commit -q -m topic
    git -C "${d}" checkout -q master
    printf 'x\n' >"${d}/bin-change"
    git -C "${d}" add bin-change
    git -C "${d}" -c user.email=t@t -c user.name=t commit -q -m "base moved"
    if [ "${merge}" = yes ]; then
        git -C "${d}" -c user.email=t@t -c user.name=t merge -q --no-ff -m merge topic
    fi
}

test_pr_mode() {
    local d
    printf 'pr mode reads only what the merge commit adds to the base\n'
    d="${WORKROOT}/pr-merge"
    make_pr_repo "${d}" yes
    assert_eq "docs-only PR over a moved base runs nothing" "$(only)" \
        "$( (cd "${d}" && GITHUB_OUTPUT='' bash "${CLASSIFIER}" pr) | tr '\n' ' ' | sed 's/ $//')"
    d="${WORKROOT}/pr-nomerge"
    make_pr_repo "${d}" no
    assert_eq "HEAD not a merge commit runs everything" "${ALL_TRUE}" \
        "$( (cd "${d}" && GITHUB_OUTPUT='' bash "${CLASSIFIER}" pr 2>/dev/null) | tr '\n' ' ' | sed 's/ $//')"
}

test_github_output() {
    local d="${WORKROOT}/empty" out="${WORKROOT}/gh_output"
    printf 'Outputs land in GITHUB_OUTPUT\n'
    : >"${out}"
    (cd "${d}" && printf 'chores/x.py\n' | GITHUB_OUTPUT="${out}" bash "${CLASSIFIER}" classify >/dev/null)
    assert_eq "seven lines written" "7" "$(wc -l <"${out}" | tr -d ' ')"
    assert_eq "chores=true written" "chores=true" "$(grep '^chores=' "${out}")"
}

# --- Main ---

main() {
    WORKROOT="$(mktemp -d)"
    test_inert
    test_catch_all
    test_trees
    test_shebang
    test_gate_files
    test_union
    test_pr_mode
    test_github_output
    printf '\n%d run, %d passed, %d failed\n' "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
