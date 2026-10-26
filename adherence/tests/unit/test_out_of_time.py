"""CI out of time is coverage (DESIGN.ARCH-ADHERENCE.md, Behaviors;
ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Key Decisions: the
bound is a deadline, not a clock): judge_change driven by its signature
with the `ci` stage's deadline set and a fake behind every port. The core
reads no time and makes no port call after the first TimedOut."""

from __future__ import annotations

from adherence.adapters.fakes import (
    FakeCodeModel,
    FakeComplexity,
    FakeDecision,
    FakeDuplication,
    FakeRecords,
    FakeReportStore,
    FakeRepository,
    FakeReviews,
)
from adherence.application.judge import judge_change
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import CodeLanguage
from adherence.domain.questions import Unavailable
from adherence.domain.report import Verdict
from adherence.domain.target import Change
from tests.judge_kit import BASE, HEAD, REPOSITORY, RULES, with_declaration
from tests.measure_kit import parameters

# The job's remaining time, as an instant no fake's frozen clock has reached:
# only the complexity tooling, scripted to, runs out of it.
CI_DEADLINE = Deadline(epoch_seconds=2e9)


def test_judge_change_out_of_time_reports_the_rest_as_coverage() -> None:
    """Given a CI run whose time ends while complexity is measured at the
    head, When the change is judged, Then the checks that did not finish are
    coverage, the verdict is inconclusive, and no port is asked anything
    after the first TimedOut."""
    repository = FakeRepository(
        {
            BASE: with_declaration({RULES: b"x = 1\n"}),
            HEAD: with_declaration({RULES: b"x = 2\n"}),
        }
    )
    complexity = FakeComplexity(TimedOut("measure complexity"))
    duplication = FakeDuplication()
    records = FakeRecords({})
    store = FakeReportStore()

    report = judge_change(
        Change(REPOSITORY, BASE, HEAD),
        repository=repository,
        reviews=FakeReviews(),
        analyzers={CodeLanguage.PYTHON: FakeCodeModel()},
        complexity=complexity,
        duplication=duplication,
        records=records,
        judge=FakeDecision(Unavailable("no judge in the unit tier")),
        reports=store,
        parameters=parameters(),
        deadline=CI_DEADLINE,
    )

    assert report.verdict is Verdict.INCONCLUSIVE
    timed_out = {c.check for c in report.coverage if "timed out" in c.reason}
    assert {"Complexity", "Duplication"} <= timed_out
    assert complexity.asked == 1
    assert duplication.asked == 0
    assert records.asked == []
    assert store.asked == []
    assert ("tree", BASE) not in repository.asked
