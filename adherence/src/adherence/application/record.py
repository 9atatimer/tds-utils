"""application/record.py -- record_report: keep a run's report.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Persistence: the CLI
calls it after judge_change, so writing the report can never touch the
verdict; a failure comes back on Recorded as the notice the presenter
shows beside the report.
"""

from __future__ import annotations

from adherence.domain.report import Recorded, Report
from adherence.ports.report_store import ReportStore


def record_report(report: Report, *, reports: ReportStore) -> Recorded:
    """Keep the report; whether it held, and, when it did not, why."""
    return reports.put(report)
