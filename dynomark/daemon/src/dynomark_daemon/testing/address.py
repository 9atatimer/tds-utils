"""An in-memory ``AddressVetPort``: hosts resolve from a table, the domain's
policy judges them, and every URL asked about is recorded."""

from collections.abc import Mapping, Sequence

from dynomark_daemon.domain.vetting import (
    AddressPolicy,
    UrlVerdict,
    VetRefusal,
    address_of,
    host_and_port,
    is_public,
    judge,
)


class FakeAddressVet:
    def __init__(
        self,
        *,
        resolves: Mapping[str, Sequence[str]],
        allowed: AddressPolicy = is_public,
    ) -> None:
        self._resolves = dict(resolves)
        self._allowed = allowed
        self.asked: list[str] = []

    def vet(self, url: str) -> UrlVerdict:
        self.asked.append(url)
        target = host_and_port(url)
        if target is None:
            return UrlVerdict(VetRefusal.UNRESOLVED)
        host, _ = target
        if host in self._resolves:
            return judge(self._resolves[host], self._allowed)
        if address_of(host) is not None:
            # A literal address resolves to itself, as getaddrinfo answers it.
            return judge((host,), self._allowed)
        return UrlVerdict(VetRefusal.UNRESOLVED)
