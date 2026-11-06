"""The tiered ReportStore, ci's (ARCHITECTURE.ARCH-ADHERENCE.md, Module
map: adapters/tiered_store.py; Where it runs): `get` reads only the
warehouse's lookup key, never the runner's file cache, and `put` writes
both. Until the warehouse is provisioned (tds-internal Issue#276) the
report is kept in the file cache alone, no base is read back, and the
notice says so; nothing about keeping it touches the verdict.
"""

from __future__ import annotations

from pathlib import Path

from adherence.adapters.fakes import FakeReportStore
from adherence.adapters.tiered_store import TieredReportStore, Unprovisioned
from adherence.ports.report_store import ReportStore, StoreMiss
from tests.report_store_contract import (
    IDENTITY,
    NOW,
    REPORT,
    REVISION,
    ReportStoreContract,
)

UNPROVISIONED = Unprovisioned("the warehouse is not provisioned (Issue#276)")


class TestTieredReportStore(ReportStoreContract):
    def store_with(self, tmp_path: Path, *, now: float = NOW) -> ReportStore:
        return TieredReportStore(
            warehouse=FakeReportStore(now=now), cache=FakeReportStore(now=now)
        )


def test_put_writes_the_warehouse_and_the_cache() -> None:
    """Given a warehouse and a file cache, When a report is put, Then each
    keeps it and the write held."""
    warehouse, cache = FakeReportStore(), FakeReportStore()
    store = TieredReportStore(warehouse=warehouse, cache=cache)

    recorded = store.put(REPORT)

    assert recorded.kept and recorded.notice is None
    assert warehouse.scanned == [REPORT]
    assert cache.scanned == [REPORT]


def test_get_reads_the_warehouse_and_never_the_cache() -> None:
    """Given a report kept only in the runner's file cache, When a base is
    got, Then the answer is the warehouse's miss: a cache a pull request's
    run could have written on a shared runner never keys a base."""
    warehouse, cache = FakeReportStore(), FakeReportStore()
    cache.put(REPORT)
    store = TieredReportStore(warehouse=warehouse, cache=cache)

    answer = store.get("example", REVISION, IDENTITY.digest, None)

    assert isinstance(answer, StoreMiss)
    assert warehouse.asked == [("example", REVISION)]
    assert cache.asked == []


def test_a_failed_warehouse_write_is_not_kept_and_says_why() -> None:
    """Given a warehouse whose write fails, When a report is put, Then the
    file cache still keeps it, the write did not hold, and the notice
    carries the warehouse's reason."""
    cache = FakeReportStore()
    store = TieredReportStore(
        warehouse=FakeReportStore(failing="the bucket refused"), cache=cache
    )

    recorded = store.put(REPORT)

    assert not recorded.kept
    assert recorded.notice is not None
    assert "the bucket refused" in recorded.notice.message
    assert cache.scanned == [REPORT]


def test_unprovisioned_keeps_the_report_in_the_cache_and_says_so() -> None:
    """Given no warehouse provisioned, When a report is put, Then the file
    cache keeps it, the write did not hold durably, and the notice says
    the report is in the runner's file cache only and why."""
    cache = FakeReportStore()
    store = TieredReportStore(warehouse=UNPROVISIONED, cache=cache)

    recorded = store.put(REPORT)

    assert cache.scanned == [REPORT]
    assert not recorded.kept
    assert recorded.notice is not None
    assert "file cache only" in recorded.notice.message
    assert UNPROVISIONED.reason in recorded.notice.message


def test_unprovisioned_reads_no_base_and_says_why() -> None:
    """Given no warehouse provisioned and a report in the file cache, When a
    base is got, Then the answer is a miss naming why, so the base is
    measured again rather than read from the runner."""
    cache = FakeReportStore()
    cache.put(REPORT)
    store = TieredReportStore(warehouse=UNPROVISIONED, cache=cache)

    answer = store.get("example", REVISION, IDENTITY.digest, None)

    assert isinstance(answer, StoreMiss)
    assert UNPROVISIONED.reason in answer.reason
    assert cache.asked == []
