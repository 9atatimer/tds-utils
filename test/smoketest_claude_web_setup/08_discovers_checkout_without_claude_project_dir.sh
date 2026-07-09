#!/usr/bin/env bash
# Given a checkout reachable only by scanning (CLAUDE_PROJECT_DIR unset, as in
# the real Claude web setup stage), When setup.sh runs, Then it DISCOVERS the
# checkout and says so.
#
# This is the bug that made every web run a silent no-op (#118): setup.sh asked
# for $CLAUDE_PROJECT_DIR, which that stage never sets, and concluded there was
# no repo -- while the checkout sat in plain sight at /home/user/tds-utils.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_setup || return 1
    local dir rc root
    dir="$(scenario_dir discover)"
    make_npm_stub "${dir}/bin"
    mkdir -p "${dir}/clones"
    make_checkout "${dir}/clones/tds-utils" >/dev/null
    # discover_checkout prints the physical path (pwd -P); on macOS /var is a
    # symlink to /private/var, so resolve the expectation the same way.
    root="$(cd "${dir}/clones/tds-utils" && pwd -P)"

    # CLAUDE_PROJECT_DIR deliberately unset; only the scan can find it.
    rc="$(SETUP_SCAN_ROOTS="${dir}/clones/*" run_setup "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_stderr_contains "${dir}" "checkout discovered at ${root}" \
        "the checkout is found by scanning, with no CLAUDE_PROJECT_DIR" || return 1
}

main "$@"
