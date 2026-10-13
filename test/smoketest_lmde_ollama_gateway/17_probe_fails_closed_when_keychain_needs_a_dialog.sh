#!/usr/bin/env bash
# 17_probe_fails_closed_when_keychain_needs_a_dialog.sh
# Given a keychain the framework checker could reach only through a dialog
# (it answers errSecInteractionNotAllowed, exit 3 -- its lookups are
# attribute-only and should never meet one, so this is the fail-closed
# backstop, not an expected state), When the probe runs
# in either mode, Then it fails closed without ever asking: the check names
# the dialog and the fix (re-run setup.sh, or unlock the keychain), and
# /usr/bin/security -- which cannot switch Keychain UI off -- is not
# attempted at all. When the launcher meets that control failure, it
# refuses once for the attempt, exits 78 and starts nothing, so each
# launchd relaunch (throttled) logs one refusal and raises no dialog
# (tds-utils Issue#441; G7).
#
# The dialog case is simulated by a fake checker beside a copy of the
# probe, so nothing here can raise a real one.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

# fake_component -- a copy of the component whose framework checker answers
# as a lookup refused for want of a dialog would.
fake_component() {
    local copy="${WORK}/component"
    cp -R "${COMPONENT_DIR}" "${copy}"
    cat > "${copy}/libexec/keychain-probe.py" <<'FAKE'
import sys
print("keychain-probe: status -25308 (user interaction off)")
sys.exit(3)
FAKE
    echo "${copy}"
}

main() {
    require_macos
    fixture_setup
    install_fake_ollama
    OLLAMA_PORT="$(free_port)"
    local copy args=() line out status=0 refusals
    copy="$(fake_component)"
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(/bin/zsh -f "${copy}/libexec/probe.zsh" control "${args[@]}" 2>&1)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "control must fail when the canary needs a dialog; output:
${out}"
    assert_contains "${out}" "FAIL keychain-framework-denied" "framework control fails"
    assert_contains "${out}" "dialog" "the failure names the dialog it refused to raise"
    assert_contains "${out}" "setup.sh" "the failure names the fix"
    assert_contains "${out}" "FAIL keychain-cli-denied" "cli control fails closed"
    assert_contains "${out}" "not attempted" "/usr/bin/security is not tried after a refusal"

    status=0
    out="$(/bin/zsh -f "${copy}/libexec/probe.zsh" confined "${args[@]}" 2>&1)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "confined must fail when the keychain daemon answered; output:
${out}"
    assert_contains "${out}" "FAIL keychain-framework-denied" "an answer from the daemon is not a sandbox denial"
    assert_contains "${out}" "FAIL keychain-cli-denied" "cli confined fails closed"
    assert_contains "${out}" "not attempted" "/usr/bin/security is not tried after a refusal"

    status=0
    out="$(env -i HOME="${FAKE_HOME}" PATH="${FAKE_KEG}/bin:${FAKE_BIN}:/usr/bin:/bin:/usr/sbin:/sbin" \
        OLLAMA_GATEWAY_PROBE_KEYCHAIN="${KEYCHAIN}" \
        OLLAMA_GATEWAY_OLLAMA_PORT="${OLLAMA_PORT}" \
        OLLAMA_GATEWAY_TREE="${TREE}" \
        OLLAMA_GATEWAY_PROFILE="${PROFILE}" \
        /bin/zsh -f "${copy}/libexec/launch-ollama.zsh" 2>&1)" || status=$?
    assert_eq "${status}" "78" "launcher exit status (EX_CONFIG; launchd relaunches, throttled); output: ${out}"
    refusals="$(grep -c 'refusing to start' <<<"${out}" || true)"
    assert_eq "${refusals}" "1" "one refusal per attempt"
    [[ ! -e "${WORK}/fake-ollama.out" ]] || fail "ollama was started despite the failed control pass"
}

main "$@"
