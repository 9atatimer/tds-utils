#!/usr/bin/env bash
# Given NEITHER credential environment variable is set but a working `gh` is
# on PATH, When `lmde acquire` runs, Then it resolves the credential from
# `gh auth token` and installs the fleet -- instead of returning before the
# package loop and leaving the machine unprovisioned.
#
# This is tds-utils#245. A normal interactive machine has a working `gh`
# login and an authed ~/.npmrc, and acquire consulted neither: it demanded
# GH_PAT_NAATM_PACKAGES_RO, found it unset, warned twice and exited 0. The
# failure is silent -- the run looks fine and simply installs nothing -- which
# is how ast-mcp sat on 0.2.1 while the fleet pin said 0.4.0.
#
# The `gh` here is a STUB. This asserts the resolution order and that the
# resolved value reaches the npmrc, not that the real gh works.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

# make_gh_stub <bindir> <token> -- a `gh` that answers `auth token`.
make_gh_stub() {
    local bindir="$1" token="$2"
    mkdir -p "${bindir}"
    cat > "${bindir}/gh" <<EOF
#!/usr/bin/env bash
if [ "\$1" = "auth" ] && [ "\$2" = "token" ]; then
    printf '%s\n' "${token}"
    exit 0
fi
exit 1
EOF
    chmod +x "${bindir}/gh"
}

main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc log staged
    dir="$(scenario_dir gh_credential_fallback)"
    log="${dir}/installlog"
    staged="$(stage_lmde "${dir}")"
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${log}" "0.2.5"
    make_gh_stub "${dir}/bin" "gh-resolved-token"

    # TEST_PAT="" clears BOTH credential names. config.sh sets each one
    # explicitly for exactly this reason: a real token in the developer's
    # environment would otherwise satisfy the check and mask the bug.
    rc="$(TEST_PAT="" LMDE_BIN="${staged}" run_acquire "${dir}")"

    assert_eq "${rc}" "0" "fail-open exit code" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/clai@9.9.9" \
        "clai installed -- the gh credential was resolved and used" || return 1
    assert_installed "${log}" "@nine-at-a-time-media/skills@0.2.5" \
        "skills installed -- the run reached the package loop at all" || return 1
}
main "$@"
