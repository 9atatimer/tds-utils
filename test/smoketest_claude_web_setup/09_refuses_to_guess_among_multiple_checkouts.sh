#!/usr/bin/env bash
# Given TWO valid checkouts in the scan path, When setup.sh runs, Then it
# refuses to pick one, names both, and still exits 0.
#
# A sandbox may hold more than one repo. Guessing wrong means provisioning from
# a different repo's tree -- and in the pasted shim, handing it the PAT. Refusal
# is the only safe answer (#118).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    local dir rc a b
    dir="$(scenario_dir multi)"
    make_npm_stub "${dir}/bin"
    mkdir -p "${dir}/clones"
    make_checkout "${dir}/clones/repo-a" >/dev/null
    make_checkout "${dir}/clones/repo-b" >/dev/null
    # physical paths: discover_checkout reports what `pwd -P` yields.
    a="$(cd "${dir}/clones/repo-a" && pwd -P)"
    b="$(cd "${dir}/clones/repo-b" && pwd -P)"

    rc="$(SETUP_SCAN_ROOTS="${dir}/clones/*" run_setup "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_stderr_contains "${dir}" "REFUSING to guess" "refuses rather than picking one" || return 1
    assert_stderr_contains "${dir}" "candidate: ${a}" "names the first candidate" || return 1
    assert_stderr_contains "${dir}" "candidate: ${b}" "names the second candidate" || return 1
}

main "$@"
