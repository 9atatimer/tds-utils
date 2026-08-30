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

make_gh_stub() {
    local bindir="$1" token="$2"
    mkdir -p "${bindir}"
    cat > "${bindir}/gh" <<EOF
#!/usr/bin/env bash
if [ "\$1" = "auth" ] && [ "\$2" = "token" ]; then
    for a in "\$@"; do
        if [ "\$a" = "github.com" ]; then printf '%s\n' "${token}"; exit 0; fi
    done
    exit 1
fi
exit 1
EOF
    chmod +x "${bindir}/gh"
}

main() {
    : "${SMOKE_TMP:=$(mktemp -d)}"
    require_lmde || return 1
    local dir rc staged
    dir="$(scenario_dir gh_credential_check)"
    staged="$(stage_lmde "${dir}")"
    make_npm_stub "${dir}/bin" "9.9.9" "0.4.0" "${dir}/installlog" "0.2.5"
    make_gh_stub "${dir}/bin" "gh-resolved-token"

    rc="$(TEST_PAT="" LMDE_BIN="${staged}" run_check "${dir}")"

    assert_eq "${rc}" "0" "check exits 0" || return 1
    assert_stderr_not_contains "${dir}" "advisory update check skipped" \
        "check must NOT skip when a gh login can supply the credential" || return 1
}
main "$@"
