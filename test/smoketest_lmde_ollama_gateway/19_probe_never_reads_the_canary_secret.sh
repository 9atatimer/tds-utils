#!/usr/bin/env bash
# 19_probe_never_reads_the_canary_secret.sh
# Given a keychain canary whose secret the probe's Security framework
# checker (/usr/bin/python3) cannot read without authorization -- created
# by /usr/bin/security without -A, so its access list admits only that
# tool, and a data read from python with Keychain UI off is refused
# (errSecAuthFailed, -25293), exactly as the login keychain refused the
# canary setup.sh made -- When the probe runs in control mode, Then it
# still passes: Keychain reachability is proven from the item's ATTRIBUTES,
# which no access list or partition list guards, so no secret is read, no
# dialog can be needed, and /usr/bin/security is asked without -w or -g.
# Under the profile the same attribute lookups are still denied, so the
# run token stays unreachable (G4) and the gateway can start unattended
# (G7; tds-utils Issue#441).
#
# Nothing here can raise a dialog: python reads with Keychain UI off, and
# /usr/bin/security is admitted by the canary's access list.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

# python_data_read_status -- the OSStatus of a Security framework read of
# the canary's secret from /usr/bin/python3, Keychain UI off. The secret is
# freed unread and never printed.
python_data_read_status() {
    /usr/bin/python3 - "${CANARY_SERVICE}" "${KEYCHAIN}" <<'PY'
import ctypes, ctypes.util, sys
sec = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Security"))
if sec.SecKeychainSetUserInteractionAllowed(ctypes.c_ubyte(0)) != 0:
    sys.exit("cannot switch Keychain UI off")
kc = ctypes.c_void_p(None)
if sec.SecKeychainOpen(ctypes.c_char_p(sys.argv[2].encode()), ctypes.byref(kc)) != 0:
    sys.exit("cannot open the keychain")
name = sys.argv[1].encode()
length, data = ctypes.c_uint32(0), ctypes.c_void_p(None)
status = sec.SecKeychainFindGenericPassword(kc, ctypes.c_uint32(len(name)), ctypes.c_char_p(name),
    ctypes.c_uint32(0), None, ctypes.byref(length), ctypes.byref(data), None)
if status == 0 and data.value:
    sec.SecKeychainItemFreeContent(None, data)
print(status)
PY
}

# shimmed_component -- a copy of the component whose probe runs a logging
# shim in place of /usr/bin/security, so the arguments it passes are seen.
shimmed_component() {
    local copy="${WORK}/component" shim="${WORK}/security-shim"
    cp -R "${COMPONENT_DIR}" "${copy}"
    cat > "${shim}" <<SHIM
#!/bin/sh
echo "argv \$*" >> "${WORK}/security.argv"
exec /usr/bin/security "\$@"
SHIM
    chmod +x "${shim}"
    sed -i '' "s|^readonly SECURITY_CLI=\"/usr/bin/security\"$|readonly SECURITY_CLI=\"${shim}\"|" \
        "${copy}/libexec/probe.zsh"
    grep -q "SECURITY_CLI=\"${shim}\"" "${copy}/libexec/probe.zsh" \
        || fail "fixture: could not point the probe copy at the security shim"
    echo "${copy}"
}

main() {
    require_macos
    fixture_setup
    security delete-generic-password -s "${CANARY_SERVICE}" "${KEYCHAIN}" >/dev/null 2>&1
    security add-generic-password -s "${CANARY_SERVICE}" -a ollama-gateway \
        -w "not-a-secret" "${KEYCHAIN}" >/dev/null
    local refused
    refused="$(python_data_read_status)"
    [[ "${refused}" != "0" ]] \
        || fail "fixture: python can read the canary's secret, so this case would be vacuous"

    local args=() line out status=0 copy
    while IFS= read -r line; do args+=("${line}"); done < <(probe_args)

    out="$(/bin/zsh -f "${PROBE}" control "${args[@]}" 2>&1)" || status=$?
    assert_eq "${status}" "0" "control passes on a canary whose secret python cannot read (status ${refused}); output: ${out}"
    assert_contains "${out}" "ok keychain-framework-reachable" "framework reachability from attributes"
    assert_contains "${out}" "ok keychain-cli-reachable" "cli reachability from attributes"
    assert_not_contains "${out}" "not-a-secret" "control never prints the value"

    copy="$(shimmed_component)"
    status=0
    out="$(/bin/zsh -f "${copy}/libexec/probe.zsh" control "${args[@]}" 2>&1)" || status=$?
    assert_eq "${status}" "0" "control through the security shim; output: ${out}"
    [[ -s "${WORK}/security.argv" ]] || fail "the probe never asked /usr/bin/security"
    assert_contains "$(cat "${WORK}/security.argv")" "find-generic-password -s ${CANARY_SERVICE}" "the cli is asked for the canary"
    if grep -E -- ' -(w|g)( |$)' "${WORK}/security.argv" >/dev/null; then
        fail "the probe asked /usr/bin/security for the secret: $(cat "${WORK}/security.argv")"
    fi

    status=0
    out="$(sandboxed /bin/zsh -f "${PROBE}" confined "${args[@]}" 2>&1)" || status=$?
    assert_eq "${status}" "0" "confined still denies the attribute lookups; output: ${out}"
    assert_contains "${out}" "ok keychain-framework-denied" "framework denied under the profile"
    assert_contains "${out}" "ok keychain-cli-denied" "cli denied under the profile"
}

main "$@"
