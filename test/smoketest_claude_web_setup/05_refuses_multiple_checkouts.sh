#!/usr/bin/env bash
# Given TWO valid checkouts in the scan path, When setup.sh runs, Then it names
# both, does NOT invoke lmde acquire from either, and still exits 0.
#
# A sandbox may hold more than one repo. Guessing wrong means running a
# different repo's bin/lmde -- and, in the pasted shim, handing it the PAT.
# Refusal is the only safe answer (#118); retains 09's refusal semantics.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    local dir rc a b rec
    dir="$(scenario_dir multi)"
    mkdir -p "${dir}/clones"
    make_checkout "${dir}/clones/repo-a" >/dev/null
    make_checkout "${dir}/clones/repo-b" >/dev/null
    a="$(cd "${dir}/clones/repo-a" && pwd -P)"
    b="$(cd "${dir}/clones/repo-b" && pwd -P)"

    rc="$(SETUP_SCAN_ROOTS="${dir}/clones/*" run_setup "${dir}")"
    rec="$(lmde_record "${dir}/home")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_stderr_contains "${dir}" "REFUSING to guess" "refuses rather than picking one" || return 1
    assert_stderr_contains "${dir}" "candidate: ${a}" "names the first candidate" || return 1
    assert_stderr_contains "${dir}" "candidate: ${b}" "names the second candidate" || return 1
    assert_file_absent "${rec}" "lmde acquire is NOT invoked when the checkout is ambiguous" || return 1
}

main "$@"
