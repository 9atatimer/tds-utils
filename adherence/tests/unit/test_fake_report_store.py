"""The fake ReportStore passes the same contract as the file store."""

from __future__ import annotations

from pathlib import Path

from adherence.adapters.fakes import FakeReportStore
from adherence.ports.report_store import ReportStore
from tests.report_store_contract import NOW, ReportStoreContract


class TestFakeReportStore(ReportStoreContract):
    def store_with(self, tmp_path: Path, *, now: float = NOW) -> ReportStore:
        return FakeReportStore(now=now)
