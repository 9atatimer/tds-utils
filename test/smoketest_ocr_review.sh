#!/usr/bin/env bash
# smoketest_ocr_review.sh -- run the OCR on Demand node suites (lib/ocr-review,
# bin/ocr-review, the workflow files), a usage check of bin/ocr-review, and
# `bin/ocr-review host-tools` against a fake runner PATH (the real PATH
# lookup, which the node suites fake). No network.
#
# Requires node >= 20 on PATH. Exit 0 = pass. Side effects: a temp dir,
# removed on exit.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH=""

# --- Action functions ---

run_suites() {
    node --test \
        "${REPO_ROOT}/test/ocr_review_authorize.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_gateway.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_host_tools.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_reaction.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_verdict.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_record.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_io.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_workflow.test.mjs" \
        "${REPO_ROOT}/test/ocr_review_stats.test.mjs"
}

check_usage_error() {
    local out
    # An unknown subcommand fails fast with the usage line and touches nothing.
    if out=$(node "${REPO_ROOT}/bin/ocr-review" frobnicate 2>&1); then
        echo "FAIL: bin/ocr-review accepted an unknown subcommand" >&2
        return 1
    fi
    grep -q 'usage: ocr-review' <<< "${out}"
    echo "PASS: bin/ocr-review usage error"
}

cleanup() {
    if [[ -n "${SCRATCH}" ]]; then
        rm -rf "${SCRATCH}"
    fi
}

# A fake runner bin dir holding executable stubs for the named tools.
make_bin_dir() {
    local dir="$1" tool
    shift
    mkdir -p "${dir}"
    for tool in "$@"; do
        printf '#!/bin/sh\nexit 0\n' > "${dir}/${tool}"
        chmod 755 "${dir}/${tool}"
    done
}

# One step output's value from a GITHUB_OUTPUT file (name<<delim / value).
step_output() {
    local file="$1" name="$2"
    grep -A1 "^${name}<<" "${file}" | tail -n 1 || true
}

# Run the host-tools step the way the review job does: node by path, the
# runner's PATH (here only the fake bin dirs), a GITHUB_OUTPUT file.
# Prints the exit code.
run_host_tools() {
    local path="$1" out_file="$2" node_bin code=0
    node_bin="$(command -v node)"
    : > "${out_file}"
    PATH="${path}" GITHUB_OUTPUT="${out_file}" "${node_bin}" "${REPO_ROOT}/bin/ocr-review" host-tools > /dev/null || code=$?
    echo "${code}"
}

expect_equal() {
    local label="$1" want="$2" got="$3"
    if [[ "${got}" != "${want}" ]]; then
        echo "FAIL: ${label}: want '${want}', got '${got}'" >&2
        return 1
    fi
}

check_host_tools() {
    local out="${SCRATCH}/github_output" code

    # The pool image: op on PATH (tools split over two PATH entries).
    make_bin_dir "${SCRATCH}/pool-a" git
    make_bin_dir "${SCRATCH}/pool-b" op
    code=$(run_host_tools "${SCRATCH}/pool-a:${SCRATCH}/pool-b" "${out}")
    expect_equal "pool image exit" 0 "${code}"
    expect_equal "pool image install_op" false "$(step_output "${out}" install_op)"

    # GitHub-hosted: no op; a non-executable file named op does not count.
    make_bin_dir "${SCRATCH}/hosted" git unzip gpg
    printf 'not a program\n' > "${SCRATCH}/hosted/op"
    chmod 644 "${SCRATCH}/hosted/op"
    code=$(run_host_tools "${SCRATCH}/hosted" "${out}")
    expect_equal "hosted exit" 0 "${code}"
    expect_equal "hosted install_op" true "$(step_output "${out}" install_op)"

    # The #446 runner: no op, and a directory named gpg is not gpg.
    make_bin_dir "${SCRATCH}/bare" git unzip
    mkdir -p "${SCRATCH}/bare/gpg"
    code=$(run_host_tools "${SCRATCH}/bare" "${out}")
    expect_equal "no-gpg exit" 1 "${code}"
    expect_equal "no-gpg cause" runner-tool-missing "$(step_output "${out}" cause)"
    expect_equal "no-gpg detail" gpg "$(step_output "${out}" detail)"

    echo "PASS: bin/ocr-review host-tools against a fake runner PATH"
}

# --- Flow functions ---

run_all() {
    run_suites
    check_usage_error
    check_host_tools
}

# --- Main ---

main() {
    SCRATCH="$(mktemp -d)"
    trap cleanup EXIT INT TERM HUP
    run_all
}

main "$@"
