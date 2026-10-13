"""keychain-probe.py -- can this process retrieve a keychain item's secret
through the Security framework? One of the G4 probe's means
(docs/design/OLLAMA-GATEWAY.DESIGN.md, G4): the probe asks it to fetch the
non-secret canary item, unconfined (must succeed) and under the sandbox
profile (must fail).

Usage: keychain-probe.py <service> [<keychain-path>]

Exit 0 when the item's secret was retrieved, 1 when it was not (not found,
denied, daemon unreachable), 2 on a usage error. Prints only the Security
framework status code -- never the secret, its length, or any attribute.

It never raises a Keychain dialog (tds-utils Issue#441; G7: no start needs
a human). Before any lookup it switches the Security framework's user
interaction off for this process, so a lookup that would need one (a
locked keychain, an access list that does not admit this binary) returns
errSecInteractionNotAllowed instead of prompting. The switch is read back
and reported on every answer; if it cannot be confirmed off, nothing is
looked up.

Stdlib only (ctypes), so it runs under /usr/bin/python3 with nothing
installed.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

USAGE = "usage: keychain-probe.py <service> [<keychain-path>]"


def load_security() -> ctypes.CDLL:
    path = ctypes.util.find_library("Security")
    if path is None:
        raise OSError("Security framework not found")
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


def retrieve(sec: ctypes.CDLL, service: str, keychain: ctypes.c_void_p | None) -> int:
    """Return the OSStatus of fetching the item's secret; frees it unread."""
    name = service.encode()
    length = ctypes.c_uint32(0)
    data = ctypes.c_void_p(None)
    status = sec.SecKeychainFindGenericPassword(
        keychain,
        ctypes.c_uint32(len(name)),
        ctypes.c_char_p(name),
        ctypes.c_uint32(0),
        None,
        ctypes.byref(length),
        ctypes.byref(data),
        None,
    )
    if status == 0 and data.value:
        sec.SecKeychainItemFreeContent(None, data)
    return int(status)


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(USAGE, file=sys.stderr)
        return 2
    service = argv[1]
    try:
        sec = load_security()
        disable_user_interaction(sec)
        keychain = open_keychain(sec, argv[2]) if len(argv) == 3 else None
        status = retrieve(sec, service, keychain)
    except OSError as err:
        print(f"keychain-probe: {err}")
        return 1
    print(f"keychain-probe: status {status} (user interaction off)")
    return 0 if status == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
