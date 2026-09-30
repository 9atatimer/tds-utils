"""Clock and IdSource contract: what every use case may assume about time and ids.

Design: Behaviors are deterministic under fakes (testing skill: "never
sleep, use fake clocks"); ids are contract ``Id``s, unique in the store
(contract/v1/README.md, Envelope: "event_id ... unique in the daemon's
store, never reused").
"""

from collections.abc import Callable

import pytest

from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.wire.base import FullMatch

pytestmark = pytest.mark.contract

CLOCKS: dict[str, Callable[[], Clock]] = {"fake": lambda: FakeClock(start_ms=1_000)}
ID_SOURCES: dict[str, Callable[[], IdSource]] = {"sequential": SequentialIds}
CONTRACT_ID = FullMatch(r"^[A-Za-z0-9._:-]{1,128}$")


@pytest.fixture(params=sorted(CLOCKS))
def clock(request: pytest.FixtureRequest) -> Clock:
    return CLOCKS[request.param]()


@pytest.fixture(params=sorted(ID_SOURCES))
def ids(request: pytest.FixtureRequest) -> IdSource:
    return ID_SOURCES[request.param]()


def test_clock_now_never_goes_backwards(clock: Clock) -> None:
    """Given a clock, When read twice, Then the second reading is not earlier."""
    first = clock.now_ms()

    assert clock.now_ms() >= first >= 0


def test_ids_are_unique_contract_ids_across_kinds(ids: IdSource) -> None:
    """Given an id source, When many ids of several kinds are drawn, Then each is
    a valid contract Id and none repeats."""
    drawn = [ids.new_id(kind) for kind in ("job", "batch", "event") * 50]

    assert len(set(drawn)) == len(drawn)
    assert all(CONTRACT_ID(value) == value for value in drawn)


def test_fake_clock_advance_moves_now_by_exactly_the_step() -> None:
    """Given a FakeClock at 1000, When advanced by 250 ms, Then now is 1250 (tests
    control time instead of sleeping)."""
    fake = FakeClock(start_ms=1_000)

    fake.advance(250)

    assert fake.now_ms() == 1_250


def test_fake_clock_refuses_to_go_backwards() -> None:
    """Given a FakeClock, When advanced by a negative step, Then it raises."""
    with pytest.raises(ValueError):
        FakeClock(start_ms=0).advance(-1)


def test_sequential_ids_are_reproducible() -> None:
    """Given two fresh SequentialIds, When drawn in the same order, Then they give
    the same ids (a test can predict them)."""
    first, second = SequentialIds(), SequentialIds()

    assert [first.new_id("job"), first.new_id("batch")] == [
        second.new_id("job"),
        second.new_id("batch"),
    ]
