"""Seam: whether a URL's host resolves only to addresses the policy allows
(Key Decisions "Background-tab capture" 2026-10-16, issue #410). Resolving
is I/O (DNS); the adapter answers with the domain's ``UrlVerdict``."""

from typing import Protocol

from dynomark_daemon.domain.vetting import UrlVerdict


class AddressVetPort(Protocol):
    def vet(self, url: str) -> UrlVerdict:
        """The verdict on an http(s) ``url``: unresolved when it names no host
        or its host does not resolve, address when any address it resolves
        to is refused, else allowed. Never raises for a URL it cannot
        resolve."""
        ...
