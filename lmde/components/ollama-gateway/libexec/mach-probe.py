"""mach-probe.py -- can this process look up a mach service by name? One
of the G4 probe's means (docs/design/OLLAMA-GATEWAY.DESIGN.md, G4): the
probe asks it, from a binary the profile does not deny by path, whether a
service the profile must deny (LaunchServices) is reachable, unconfined
(must be) and under the sandbox profile (must not be). So the denial is
proven on the mach service itself, not only on the path of the tool that
usually talks to it.

Usage: mach-probe.py <service-name>

Exit 0 when the lookup succeeded, 1 when the sandbox or the bootstrap
server refused it, 2 on usage, 3 when the service does not exist
(bootstrap's "unknown service", which proves nothing about confinement).
Prints only the bootstrap status code. Stdlib only (ctypes).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

USAGE = "usage: mach-probe.py <service-name>"
BOOTSTRAP_UNKNOWN_SERVICE = 1102
EXIT_FOUND = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_NO_SUCH_SERVICE = 3


def look_up(service: str) -> int:
    """Return bootstrap_look_up's status for the service name."""
    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    port = ctypes.c_uint32(0)
    bootstrap_port = ctypes.c_uint32.in_dll(libc, "bootstrap_port")
    return int(libc.bootstrap_look_up(bootstrap_port, service.encode(), ctypes.byref(port)))


def exit_code(status: int) -> int:
    if status == 0:
        return EXIT_FOUND
    if status == BOOTSTRAP_UNKNOWN_SERVICE:
        return EXIT_NO_SUCH_SERVICE
    return EXIT_REFUSED


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    try:
        status = look_up(argv[1])
    except OSError as err:
        print(f"mach-probe: {err}")
        return EXIT_REFUSED
    print(f"mach-probe: status {status}")
    return exit_code(status)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
