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
from ipaddress import IPv4Address, IPv6Address, IPv6Network, ip_address
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


NAT64_WELL_KNOWN: Final = IPv6Network("64:ff9b::/96")
"""RFC 6052: a DNS64 network's answer for an IPv4-only host; the low 32 bits
are the IPv4 address the NAT64 gateway connects to."""
IPV4_EMBEDDING: Final = (
    IPv6Network("64:ff9b:1::/48"),
    IPv6Network("::/96"),
    IPv6Network("2002::/16"),
)
"""Blocks whose addresses reach an IPv4 address they carry: local-use NAT64
(RFC 8215, low 32 bits), IPv4-compatible ``::a.b.c.d`` (deprecated, low 32
bits) and 6to4 (RFC 3056, bits 16-48). Each is judged by its IPv4 address
too, so none is more public than the address it carries."""
SITE_LOCAL: Final = IPv6Network("fec0::/10")
"""Deprecated site-local (RFC 3879): an intranet address."""


# --- Pure helpers (embedded IPv4) ---


def embedded_ipv4(address: IPv6Address) -> IPv4Address | None:
    """The IPv4 address an IPv6 address carries, or ``None``: mapped, NAT64
    (well-known and local-use), IPv4-compatible and 6to4."""
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address in NAT64_WELL_KNOWN or any(address in n for n in IPV4_EMBEDDING):
        return IPv4Address(int(address) & 0xFFFFFFFF)
    return None


# --- Predicates ---


def _is_global_unicast(address: IPAddress) -> bool:
    return address.is_global and not address.is_multicast


def is_public(address: IPAddress) -> bool:
    """A globally routable unicast address: never loopback, link-local,
    private, unspecified, reserved, site-local or multicast. An IPv6 address
    carrying an IPv4 address is never more public than it: an IPv4-mapped
    one, or one through the NAT64 well-known prefix, is judged as its IPv4
    address; the other carrying forms must pass both. The default policy."""
    if isinstance(address, IPv4Address):
        return _is_global_unicast(address)
    if address in SITE_LOCAL:
        return False
    carried = embedded_ipv4(address)
    if carried is None:
        return _is_global_unicast(address)
    if address.ipv4_mapped is not None or address in NAT64_WELL_KNOWN:
        return _is_global_unicast(carried)
    return _is_global_unicast(carried) and _is_global_unicast(address)


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
