#!/usr/bin/env bash
# 03_probe_catches_a_keychain_hole.sh
# Given a profile that still denies exec of /usr/bin/security but admits
# the keychain daemons' mach services (an allow appended after the
# denials, so it wins), When the probe runs under it, Then
# keychain-framework-denied fails: the run token is retrievable through
# the Security framework, so the probe refuses even though the path-based
# and exec-based rules still hold (G4: "by any means, not only by path").

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    local holed="${WORK}/holed.sb" args=() line out status=0
    grep -q 'SecurityServer' "${PROFILE}" || fail "profile has no keychain mach-lookup denial to undo"
    { cat "${PROFILE}"; printf '(allow mach-lookup (global-name-regex #"^com\\.apple\\.(SecurityServer|securityd|secd|security\\.)"))\n'; } > "${holed}"
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(sandboxed_with "${holed}" /bin/zsh -f "${PROBE}" confined "${args[@]}" 2>&1)" || status=$?

    [[ "${status}" -ne 0 ]] || fail "probe must refuse a profile with a keychain hole; output:
${out}"
    assert_contains "${out}" "FAIL keychain-framework-denied" "framework retrieval through the hole"
    assert_contains "${out}" "ok canary-file-unreadable" "the rest of the profile still holds"
}

main "$@"
