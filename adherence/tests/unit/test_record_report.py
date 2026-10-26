"""record_report, the use case behind "A report persists" (DESIGN.ARCH-
ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface),
driven by its signature with the fake ReportStore."""

from __future__ import annotations

from dataclasses import replace

from adherence.adapters.fakes import FakeReportStore
from adherence.application.record import record_report
from adherence.domain.report import Verdict
from tests.judge_kit import RULES, judge_with, stubbed

STUBBED = b"\ndef tidy():\n    pass\n"


def test_record_report_keeps_a_judged_report_with_its_repository_and_change() -> None:
    """Given a completed run, When it reports, Then the report is kept with
    the repository and the change it judged."""
    report = judge_with({}, {RULES: STUBBED}, when={STUBBED: stubbed(RULES, "tidy", 2)})
    store = FakeReportStore()

    recorded = record_report(report, reports=store)

    assert recorded.kept and recorded.notice is None
    (kept,) = store.scanned
    assert kept == report
    assert (kept.repository, kept.revision) == ("example", "c" * 40)


def test_record_report_that_fails_never_changes_the_verdict() -> None:
    """Given a store that cannot keep the report, When the run reports, Then
    the failure comes back as a notice and the report and its verdict are as
    judged."""
    report = judge_with({}, {RULES: STUBBED}, when={STUBBED: stubbed(RULES, "tidy", 2)})
    before = replace(report)

    recorded = record_report(
        report, reports=FakeReportStore(failing="the disk is full")
    )

    assert not recorded.kept
    assert recorded.notice is not None and "the disk is full" in recorded.notice.message
    assert report == before and report.verdict is not None
    assert report.verdict is not Verdict.NOT_RUN
