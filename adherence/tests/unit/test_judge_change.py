"""judge_change, the gate's core (DESIGN.ARCH-ADHERENCE.md, Judging a change
and Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface), driven
by its signature with a fake behind every port."""

from __future__ import annotations

from adherence.domain.finding import Provenance
from adherence.domain.report import Verdict
from tests.judge_kit import RULES, judge_with, stubbed

STUBBED = b"\ndef tidy():\n    pass\n"
FIXED = b"\ndef tidy():\n    return 1\n"


def test_judge_change_that_removes_a_finding_is_raised() -> None:
    """Given a base finding absent at the head, on a unit the head still
    covers and a check that ran there and passed, with nothing introduced,
    When the change is judged, Then the verdict is raised and the report
    names the removed finding."""
    report = judge_with(
        {RULES: STUBBED},
        {RULES: FIXED},
        when={
            STUBBED: stubbed(RULES, "tidy", 2),
            FIXED: stubbed(RULES, "tidy", 2, stub=None),
        },
    )

    assert report.verdict is Verdict.RAISED
    (removed,) = report.removed
    assert (removed.check.name, removed.unit.path, removed.unit.symbol) == (
        "Stub",
        RULES,
        "tidy",
    )
    assert report.findings == ()


def test_judge_change_that_introduces_a_finding_is_lowered() -> None:
    """Given a change that introduces a finding, When it is judged, Then the
    verdict is lowered and the report names the finding, marked introduced.
    (A judged finding's confidence is task-064's: no judged check runs yet.)"""
    report = judge_with(
        {RULES: FIXED},
        {RULES: STUBBED},
        when={
            STUBBED: stubbed(RULES, "tidy", 2),
            FIXED: stubbed(RULES, "tidy", 2, stub=None),
        },
    )

    assert report.verdict is Verdict.LOWERED
    (finding,) = report.findings
    assert (finding.check.name, finding.unit.symbol) == ("Stub", "tidy")
    assert finding.provenance is Provenance.INTRODUCED
    assert report.removed == ()
