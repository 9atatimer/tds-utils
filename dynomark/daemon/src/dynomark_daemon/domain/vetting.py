"""The address policy a URL is held to before anything loads it with the
user's session or from the daemon (DYNOMARK.DESIGN.md, Security
Considerations "Daemon-side fetch"; Key Decisions "Background-tab capture"
2026-10-16, issue #410).

One policy for both capture paths: the daemon's fetch fallback connects only
to addresses it allows, and the writer's background tab opens only a URL
whose every address it allows. Resolving a host is I/O and stays at the
edge; the judgement over the addresses is here.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Final
from urllib.parse import urlsplit

# --- Constants ---

IPAddress = IPv4Address | IPv6Address
AddressPolicy = Callable[[IPAddress], bool]
"""Whether an address may be loaded (every one a host resolves to must pass)."""

DEFAULT_PORTS: Final = {"http": 80, "https": 443}


class VetRefusal(StrEnum):
    """Why a URL may not be loaded (contract v2 ``VetRefusal``)."""

    SCHEME = "scheme"
    """Not http(s)."""
    UNRESOLVED = "unresolved"
    """No host, or the host does not resolve."""
    ADDRESS = "address"
    """The host resolves to an address the policy refuses."""


@dataclass(frozen=True, slots=True)
class UrlVerdict:
    """The vet of one URL: allowed when nothing refuses it."""

    refusal: VetRefusal | None = None

    @property
    def allowed(self) -> bool:
        return self.refusal is None


ALLOWED: Final = UrlVerdict()


# --- Predicates ---


def is_public(address: IPAddress) -> bool:
    """A globally routable unicast address: never loopback, link-local,
    private, unspecified, reserved or multicast (an IPv4-mapped IPv6 address
    is judged as its IPv4 address). The default policy."""
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def any_address(address: IPAddress) -> bool:
    """Every address: an install that loads its intranet and localhost pages
    (``[capture] private_addresses = true``)."""
    return True


# --- Pure helpers ---


def host_and_port(url: str) -> tuple[str, int] | None:
    """The host to resolve for ``url`` and the port it would connect to, or
    ``None`` when it names no usable host."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if not parts.hostname:
        return None
    return parts.hostname, port or DEFAULT_PORTS.get(parts.scheme.lower(), 80)


def address_of(text: str) -> IPAddress | None:
    """``text`` as an address (an IPv6 zone id dropped), or ``None``."""
    try:
        return ip_address(text.split("%")[0])
    except ValueError:
        return None


def judge(addresses: Sequence[str], allowed: AddressPolicy) -> UrlVerdict:
    """The verdict on a host that resolved to ``addresses``: unresolved when
    there are none (or one is not an address), refused when any one is not
    ``allowed``."""
    parsed = [address_of(a) for a in addresses]
    if not parsed or any(a is None for a in parsed):
        return UrlVerdict(VetRefusal.UNRESOLVED)
    if not all(allowed(a) for a in parsed if a is not None):
        return UrlVerdict(VetRefusal.ADDRESS)
    return ALLOWED
