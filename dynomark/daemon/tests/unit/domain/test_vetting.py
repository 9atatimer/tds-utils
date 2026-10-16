"""The address policy's judgement of one address (DYNOMARK.DESIGN.md,
Security Considerations "Daemon-side fetch"; Key Decisions "Background-tab
capture" 2026-10-16): ``is_public`` allows a globally routable unicast
address only, and an IPv6 address that carries an IPv4 address -- mapped,
NAT64, IPv4-compatible, 6to4 -- is never more public than the IPv4 address
it carries (issue #534 T5).
"""

from collections.abc import Callable
from ipaddress import IPv4Address, IPv6Address

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.vetting import is_public

# --- Embedded forms ---


def _mapped(v4: IPv4Address) -> IPv6Address:
    return IPv6Address((0xFFFF << 32) | int(v4))


def _nat64(v4: IPv4Address) -> IPv6Address:
    """The NAT64 well-known prefix 64:ff9b::/96 (RFC 6052)."""
    return IPv6Address((0x0064FF9B << 96) | int(v4))


def _nat64_local(v4: IPv4Address) -> IPv6Address:
    """The local-use NAT64 prefix 64:ff9b:1::/48 (RFC 8215), IPv4 in the
    low 32 bits."""
    return IPv6Address((0x0064FF9B0001 << 80) | int(v4))


def _compatible(v4: IPv4Address) -> IPv6Address:
    """A deprecated IPv4-compatible address ::a.b.c.d."""
    return IPv6Address(int(v4))


def _six_to_four(v4: IPv4Address) -> IPv6Address:
    """6to4 2002:a.b.c.d::/48 (RFC 3056)."""
    return IPv6Address((0x2002 << 112) | (int(v4) << 80) | 1)


EMBEDDINGS: dict[str, Callable[[IPv4Address], IPv6Address]] = {
    "mapped": _mapped,
    "nat64": _nat64,
    "nat64-local": _nat64_local,
    "ipv4-compatible": _compatible,
    "6to4": _six_to_four,
}

NON_PUBLIC_V4 = st.sampled_from(
    [
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "0.0.0.0/8",
        "224.0.0.0/4",
        "240.0.0.0/4",
    ]
).flatmap(
    lambda net: st.integers(
        min_value=int(IPv4Address(net.split("/")[0])),
        max_value=int(IPv4Address(net.split("/")[0]))
        + 2 ** (32 - int(net.split("/")[1]))
        - 1,
    ).map(IPv4Address)
)


# --- Properties ---


@pytest.mark.parametrize("form", sorted(EMBEDDINGS))
@given(v4=NON_PUBLIC_V4)
def test_an_ipv6_address_embedding_a_non_public_ipv4_is_refused(
    form: str, v4: IPv4Address
) -> None:
    """Given a loopback, private, link-local, shared, unspecified, multicast or
    reserved IPv4 address, When it is embedded in an IPv6 address (mapped,
    NAT64, local-use NAT64, IPv4-compatible or 6to4), Then the policy refuses
    it: a NAT64 or 6to4 path reaches the IPv4 address it carries."""
    assert not is_public(v4)
    assert not is_public(EMBEDDINGS[form](v4))


@pytest.mark.parametrize("form", ["mapped", "nat64"])
def test_a_public_ipv4_embedded_in_a_translating_prefix_is_allowed(form: str) -> None:
    """Given a public IPv4 address, When it arrives IPv4-mapped or through the
    NAT64 well-known prefix (a DNS64 network's answer), Then it is allowed,
    as the IPv4 address itself is."""
    v4 = IPv4Address("93.184.216.34")

    assert is_public(v4) and is_public(EMBEDDINGS[form](v4))


@pytest.mark.parametrize("text", ["fec0::1", "feff:ffff::1", "fec0:1:2:3::4"])
def test_a_deprecated_site_local_ipv6_address_is_refused(text: str) -> None:
    """Given an address in the deprecated site-local block fec0::/10, When it
    is judged, Then it is refused (it was an intranet address)."""
    assert not is_public(IPv6Address(text))


def test_a_global_ipv6_address_is_allowed() -> None:
    """Given a globally routable IPv6 unicast address, When it is judged, Then
    it is allowed (the accept case of the refusals above)."""
    assert is_public(IPv6Address("2606:4700:4700::1111"))
