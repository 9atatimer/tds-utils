"""Use case: a URL is vetted before a background tab loads it (DYNOMARK.DESIGN.md,
Key Decisions "Background-tab capture" 2026-10-16, issue #410)."""

import pytest

from dynomark_daemon.app.vet import vet_url
from dynomark_daemon.domain.vetting import VetRefusal
from dynomark_daemon.testing.address import FakeAddressVet


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "chrome://settings/", "javascript:alert(1)"]
)
def test_vet_url_refuses_a_non_http_url_without_resolving_it(url: str) -> None:
    """Given a URL that is not http(s), When vetted, Then it is refused scheme
    and the address port is never asked."""
    vetter = FakeAddressVet(resolves={})

    verdict = vet_url(url, vetter=vetter)

    assert (verdict.allowed, verdict.refusal) == (False, VetRefusal.SCHEME)
    assert vetter.asked == []


def test_vet_url_asks_the_address_policy_for_an_http_url() -> None:
    """Given an http(s) URL, When vetted, Then the address port decides."""
    vetter = FakeAddressVet(resolves={"intranet.example": ("10.0.0.5",)})

    verdict = vet_url("https://intranet.example/", vetter=vetter)

    assert verdict.refusal is VetRefusal.ADDRESS
    assert vetter.asked == ["https://intranet.example/"]
