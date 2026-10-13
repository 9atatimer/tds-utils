"""keychain-probe.py -- can this process reach a keychain item through the
Security framework? One of the G4 probe's means
(docs/design/OLLAMA-GATEWAY.DESIGN.md, G4): the probe asks it to find the
non-secret canary item, unconfined (must succeed) and under the sandbox
profile (must fail).

Usage: keychain-probe.py <service> [<keychain-path>]

Exit 0 when the item was found, 1 when it was not (not found, denied,
daemon unreachable), 2 on a usage error, 3 when the keychain answered but
refused for want of a dialog (errSecInteractionNotAllowed). Prints only
the Security framework status code -- never the secret, its length, or
any attribute.

It never reads the item's secret (tds-utils Issue#441). The lookup asks
for the item alone, no password data, so the item's access list and
partition list -- which guard the secret, and which refused a data read
from /usr/bin/python3 on the login keychain with errSecAuthFailed -- are
never evaluated, and neither is the keychain's lock: attributes read with
no authorization at all. Reachability is still the property G4 needs:
under the profile the keychain daemons are unreachable, so the item cannot
even be found, and a secret that cannot be found cannot be read.

It never raises a Keychain dialog (G7: no start needs a human). Belt and
braces over the attribute-only lookup, it switches the Security
framework's user interaction off for this process first, so anything that
would still want one returns errSecInteractionNotAllowed instead of
prompting. The switch is read back and reported on every answer; if it
cannot be confirmed off, nothing is looked up.

Stdlib only (ctypes), so it runs under /usr/bin/python3 with nothing
installed.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

USAGE = "usage: keychain-probe.py <service> [<keychain-path>]"
ERR_SEC_INTERACTION_NOT_ALLOWED = -25308
EXIT_FOUND = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2
EXIT_NEEDS_DIALOG = 3


def load_framework(name: str) -> ctypes.CDLL:
    path = ctypes.util.find_library(name)
    if path is None:
        raise OSError(f"{name} framework not found")
    return ctypes.cdll.LoadLibrary(path)


def disable_user_interaction(sec: ctypes.CDLL) -> None:
    """Switch Keychain UI off for this process and confirm it by readback.

    SecKeychainSetUserInteractionAllowed is the switch the legacy lookup
    below (SecKeychainFindGenericPassword) honours; kSecUseAuthenticationUI
    is the SecItem* equivalent and does not apply to it.
    """
    status = sec.SecKeychainSetUserInteractionAllowed(ctypes.c_ubyte(0))
    if status != 0:
        raise OSError(f"cannot switch keychain user interaction off (status {status}); not looking up")
    allowed = ctypes.c_ubyte(1)
    status = sec.SecKeychainGetUserInteractionAllowed(ctypes.byref(allowed))
    if status != 0 or allowed.value != 0:
        raise OSError("keychain user interaction is still on; not looking up")


def open_keychain(sec: ctypes.CDLL, keychain_path: str) -> ctypes.c_void_p:
    ref = ctypes.c_void_p(None)
    status = sec.SecKeychainOpen(ctypes.c_char_p(keychain_path.encode()), ctypes.byref(ref))
    if status != 0:
        raise OSError(f"SecKeychainOpen status {status}")
    return ref


def find_item(
    sec: ctypes.CDLL, cf: ctypes.CDLL, service: str, keychain: ctypes.c_void_p | None
) -> int:
    """Return the OSStatus of finding the item, attributes only.

    passwordLength and passwordData are NULL, which is the documented way
    to ask SecKeychainFindGenericPassword for the item reference without
    its data: no secret is fetched, so no access list is consulted. The
    reference is released unused.
    """
    name = service.encode()
    item = ctypes.c_void_p(None)
    status = sec.SecKeychainFindGenericPassword(
        keychain,
        ctypes.c_uint32(len(name)),
        ctypes.c_char_p(name),
        ctypes.c_uint32(0),
        None,
        None,
        None,
        ctypes.byref(item),
    )
    if item.value:
        cf.CFRelease(item)
    return int(status)


def exit_code(status: int) -> int:
    """The probe's exit code for a lookup's OSStatus."""
    if status == 0:
        return EXIT_FOUND
    if status == ERR_SEC_INTERACTION_NOT_ALLOWED:
        return EXIT_NEEDS_DIALOG
    return EXIT_NOT_FOUND


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    service = argv[1]
    try:
        sec = load_framework("Security")
        cf = load_framework("CoreFoundation")
        disable_user_interaction(sec)
        keychain = open_keychain(sec, argv[2]) if len(argv) == 3 else None
        status = find_item(sec, cf, service, keychain)
    except OSError as err:
        print(f"keychain-probe: {err}")
        return EXIT_NOT_FOUND
    print(f"keychain-probe: status {status} (user interaction off, attributes only)")
    return exit_code(status)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
