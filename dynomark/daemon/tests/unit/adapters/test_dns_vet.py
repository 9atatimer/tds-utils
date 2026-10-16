"""``DnsAddressVet``'s resolution is bounded (issue #534 T6): ``url.vet``
runs on the transport's small model pool, so a host whose DNS never answers
must not hold a pool thread past the vet's deadline. A vet that runs out of
time is answered unresolved: not allowed, fail-closed.
"""

import threading
import time
from collections.abc import Iterator, Sequence

import pytest

from dynomark_daemon.adapters.fetch import DnsAddressVet, is_public
from dynomark_daemon.domain.vetting import VetRefusal

DEADLINE_S = 0.05
"""Short enough to keep the suite fast, long enough for a resolver that
answers at once."""


class BlockingResolve:
    """A resolver whose lookups hang until released: DNS that never answers."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, host: str, port: int) -> Sequence[str]:
        self.calls += 1
        self.release.wait(5)
        return ("93.184.216.34",)


@pytest.fixture
def blocking() -> Iterator[BlockingResolve]:
    resolve = BlockingResolve()
    yield resolve
    resolve.release.set()


def test_a_vet_whose_dns_never_answers_is_unresolved_by_its_deadline(
    blocking: BlockingResolve,
) -> None:
    """Given a resolver that never answers, When two URLs are vetted one after
    the other, Then each is answered unresolved (not allowed) once its
    deadline passes, not when DNS answers: the calling thread is free again
    well before the lookup ends."""
    vet = DnsAddressVet(allowed=is_public, resolve=blocking, deadline_s=DEADLINE_S)

    started = time.monotonic()
    first = vet.vet("https://slow.example/a")
    second = vet.vet("https://slower.example/b")
    elapsed = time.monotonic() - started

    assert (first.refusal, second.refusal) == (
        VetRefusal.UNRESOLVED,
        VetRefusal.UNRESOLVED,
    )
    assert elapsed < 1.0
    assert not blocking.release.is_set()


def test_a_vet_whose_dns_answers_in_time_is_judged() -> None:
    """Given a resolver that answers at once, When a public and a private host
    are vetted under the deadline, Then the policy judges the answers (the
    accept case of the deadline)."""
    answers = {"tokio.rs": ("93.184.216.34",), "router": ("192.168.1.1",)}
    vet = DnsAddressVet(
        allowed=is_public,
        resolve=lambda host, port: answers[host],
        deadline_s=1.0,
    )

    assert vet.vet("https://tokio.rs/").allowed
    assert vet.vet("http://router/").refusal is VetRefusal.ADDRESS
