"""AddressVetPort contract: the background-tab address policy (DYNOMARK.DESIGN.md,
Key Decisions "Background-tab capture" 2026-10-16, issue #410; contract/v2
README, Background-tab capture).

The real adapter (``DnsAddressVet``) runs with a fake resolver, so no test
reaches DNS; the fake (``FakeAddressVet``) is held to the same verdicts.
Pinned for both: loopback, private, link-local, a hostname resolving to a
private address, and a public URL; and the ``[capture] private_addresses``
opt-out on the real adapter.
"""

from collections.abc import Callable, Sequence

import pytest

from dynomark_daemon.adapters.fetch import DnsAddressVet, any_address, is_public
from dynomark_daemon.domain.vetting import VetRefusal
from dynomark_daemon.ports.address import AddressVetPort
from dynomark_daemon.testing.address import FakeAddressVet

pytestmark = pytest.mark.contract

RESOLVES: dict[str, tuple[str, ...]] = {
    "127.0.0.1": ("127.0.0.1",),
    "localhost": ("127.0.0.1", "::1"),
    "::1": ("::1",),
    "192.168.1.1": ("192.168.1.1",),
    "169.254.169.254": ("169.254.169.254",),
    "intranet.example": ("10.0.0.5",),
    "tokio.rs": ("93.184.216.34",),
    "split.example": ("93.184.216.34", "10.0.0.5"),
}

CASES: list[tuple[str, VetRefusal | None]] = [
    ("http://127.0.0.1:8080/admin", VetRefusal.ADDRESS),
    ("http://localhost/", VetRefusal.ADDRESS),
    ("http://[::1]/", VetRefusal.ADDRESS),
    ("http://192.168.1.1/", VetRefusal.ADDRESS),
    ("http://169.254.169.254/latest/meta-data", VetRefusal.ADDRESS),
    ("https://intranet.example/wiki", VetRefusal.ADDRESS),
    ("https://split.example/", VetRefusal.ADDRESS),
    ("https://tokio.rs/tokio/tutorial", None),
    ("https://nowhere.invalid/", VetRefusal.UNRESOLVED),
]


def fake_resolve(host: str, port: int) -> Sequence[str]:
    """``getaddrinfo`` over ``RESOLVES``; an unknown host does not resolve."""
    if host not in RESOLVES:
        raise OSError(f"{host}: name does not resolve")
    return RESOLVES[host]


def _fake() -> AddressVetPort:
    return FakeAddressVet(resolves=RESOLVES)


def _real() -> AddressVetPort:
    return DnsAddressVet(allowed=is_public, resolve=fake_resolve)


VETTERS: dict[str, Callable[[], AddressVetPort]] = {"fake": _fake, "dns": _real}


@pytest.fixture(params=sorted(VETTERS))
def vetter(request: pytest.FixtureRequest) -> AddressVetPort:
    return VETTERS[request.param]()


@pytest.mark.parametrize(("url", "refusal"), CASES, ids=[c[0] for c in CASES])
def test_vet_applies_the_fetch_address_policy(
    vetter: AddressVetPort, url: str, refusal: VetRefusal | None
) -> None:
    """Given the default policy, When a URL is vetted, Then loopback, private,
    link-local, a name resolving to a private address (any one of its
    addresses), and a name that does not resolve are refused, and a public
    URL is allowed."""
    verdict = vetter.vet(url)

    assert (verdict.allowed, verdict.refusal) == (refusal is None, refusal)


def test_the_private_addresses_opt_out_allows_every_resolving_address() -> None:
    """Given ``[capture] private_addresses = true`` (the any-address policy),
    When loopback, private and link-local URLs are vetted, Then each is
    allowed; a name that does not resolve is still refused."""
    vetter = DnsAddressVet(allowed=any_address, resolve=fake_resolve)

    allowed = [
        vetter.vet(url).allowed
        for url in (
            "http://127.0.0.1:8080/",
            "http://192.168.1.1/",
            "http://169.254.169.254/",
            "https://intranet.example/",
        )
    ]

    assert allowed == [True, True, True, True]
    assert vetter.vet("https://nowhere.invalid/").refusal is VetRefusal.UNRESOLVED


def test_a_url_with_no_host_is_unresolved(vetter: AddressVetPort) -> None:
    """Given an http URL with no host, When vetted, Then it is refused
    unresolved (there is nothing to vet)."""
    assert vetter.vet("http:///path").refusal is VetRefusal.UNRESOLVED
