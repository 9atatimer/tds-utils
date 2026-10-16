"""Use case: a URL is vetted before the writer's extension loads it in a
background tab (DYNOMARK.DESIGN.md, Key Decisions "Background-tab capture"
2026-10-16, issue #410; contract/v2 ``url.vet``)."""

from dynomark_daemon.domain.bookmark import is_fetchable
from dynomark_daemon.domain.vetting import UrlVerdict, VetRefusal
from dynomark_daemon.ports.address import AddressVetPort


def vet_url(url: str, *, vetter: AddressVetPort) -> UrlVerdict:
    """Whether a background tab may load ``url``: http(s) only, then the
    fetch address policy over every address its host resolves to."""
    if not is_fetchable(url):
        return UrlVerdict(VetRefusal.SCHEME)
    return vetter.vet(url)
