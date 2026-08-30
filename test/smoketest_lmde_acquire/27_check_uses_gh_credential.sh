#!/usr/bin/env bash
# Given NEITHER credential environment variable is set but a working `gh` is
# on PATH, When `lmde acquire --check` runs, Then it queries the registry
# rather than reporting the advisory check skipped.
#
# Codex review on PR #246: the install path was routed through the new
# resolver but `check_run` still read the two environment variables directly,
# so on a gh-only machine installs worked while --check stayed silently
# disabled. That is the worse half of the pair -- an advisory check that
# reports nothing looks identical to one that found nothing.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"


main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc staged home
    dir="$(scenario_dir gh_credential_check)"
    home="${dir}/home"
    staged="$(stage_lmde "${dir}")"
    # Seed an installed clai BEHIND the stub's latest. Without a stamp to
    # compare against, check_one is silent and the scenario would pass on a
    # run that reached nothing at all -- rc==0 is vacuous here because --check
    # is fail-open by contract.
    seed_installed "${home}" "clai" "clai" "1.0.0" >/dev/null
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${dir}/installlog" "0.2.5"
    make_gh_stub "${dir}/bin" "gh-resolved-token"

    rc="$(TEST_PAT="" LMDE_BIN="${staged}" run_check "${dir}")"

    assert_eq "${rc}" "0" "check exits 0" || return 1
    assert_stderr_not_contains "${dir}" "advisory update check skipped" \
        "check must NOT skip when a gh login can supply the credential" || return 1
    # rc==0 proves nothing on its own -- --check is fail-open by contract, and
    # assert_stderr_not_contains passes vacuously if stderr was never written.
    # Assert the run actually REACHED the registry: with clai floating and the
    # stub reporting 9.9.9 as latest, a check that queried at all must report
    # the drift, and a check that no-opped cannot.
    assert_stdout_contains "${dir}" "clai: floating, installed 1.0.0, latest 9.9.9" \
        "check queried the registry and reported the drift" || return 1
    assert_file_absent "${dir}/installlog" \
        "--check must never install" || return 1
}
main "$@"
