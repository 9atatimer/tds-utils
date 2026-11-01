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
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Approval,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
    Unknown,
)
from adherence.domain.model import CodeLanguage
from adherence.domain.qualities import CATALOG, Quality
from adherence.domain.questions import Unavailable
from adherence.domain.report import Report, Verdict
from adherence.domain.target import Change
from tests.judge_kit import BASE, HEAD, REPOSITORY, RULES, with_declaration
from tests.measure_kit import parameters

EARLIER = "a" * 40


class _AskedReviews:
    """ReviewPort over FakeReviews that lists every commit it was asked
    about, in order."""

    def __init__(self, inner: FakeReviews) -> None:
        self._inner = inner
        self.asked: list[str] = []

    def approvals(
        self, commit: str, deadline: Deadline | None
    ) -> Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut:
        self.asked.append(commit)
        return self._inner.approvals(commit, deadline)


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


def _judged(repository: FakeRepository, store: FakeReportStore) -> Report:
    return judge_change(
        Change(REPOSITORY, BASE, HEAD),
        repository=repository,
        reviews=FakeReviews(),
        analyzers={CodeLanguage.PYTHON: FakeCodeModel()},
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords({}),
        judge=FakeDecision(Unavailable("no judge in the unit tier")),
        reports=store,
        parameters=parameters(),
        deadline=CI_DEADLINE,
    )


def test_judge_change_out_of_time_telling_the_change_is_coverage() -> None:
    """Given a CI run whose time ends before the repository can tell what
    the change did, When the change is judged, Then the verdict is
    inconclusive, never not run: every check is coverage naming the
    timeout, and nothing more is asked."""
    repository = FakeRepository(
        {
            BASE: with_declaration({RULES: b"x = 1\n"}),
            HEAD: with_declaration({RULES: b"x = 2\n"}),
        },
        now=CI_DEADLINE.epoch_seconds,
    )
    store = FakeReportStore()

    report = _judged(repository, store)

    assert report.verdict is Verdict.INCONCLUSIVE, report.reasons
    timed_out = {c.check for c in report.coverage if "timed out" in c.reason}
    assert timed_out == {c.name for c in CATALOG}
    assert report.ran == () and report.findings == ()
    assert repository.asked == [("changed", HEAD)]
    assert store.asked == []


def test_judge_change_out_of_time_listing_the_head_is_coverage() -> None:
    """Given a CI run whose time ends while the head's tree is listed, When
    the change is judged, Then the verdict is inconclusive, never not run:
    every check at the head is coverage naming the timeout, and the base is
    never asked for."""
    repository = FakeRepository(
        {
            BASE: with_declaration({RULES: b"x = 1\n"}),
            HEAD: with_declaration({RULES: b"x = 2\n"}),
        },
        unlisted_at={HEAD: TimedOut("list the tree")},
    )
    store = FakeReportStore()

    report = _judged(repository, store)

    assert report.verdict is Verdict.INCONCLUSIVE, report.reasons
    timed_out = {c.check for c in report.coverage if "list the tree" in c.reason}
    assert timed_out >= {c.name for c in CATALOG if c.quality is not Quality.DECLARED}
    assert report.findings == ()
    assert ("tree", BASE) not in repository.asked
    assert store.asked == []


def _walked(
    repository: FakeRepository, reviews: _AskedReviews, store: FakeReportStore
) -> Report:
    return judge_change(
        Change(REPOSITORY, BASE, HEAD),
        repository=repository,
        reviews=reviews,
        analyzers={CodeLanguage.PYTHON: FakeCodeModel()},
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords({}),
        judge=FakeDecision(Unavailable("no judge in the unit tier")),
        reports=store,
        parameters=parameters(),
        deadline=CI_DEADLINE,
    )


def test_judge_change_out_of_time_reading_the_reviews_is_coverage() -> None:
    """Given a CI run whose time ends while the reviews of the newest
    landing of adherence.toml are read, When the change is judged, Then the
    verdict is inconclusive with the rest as coverage naming the timeout,
    and no port is asked anything after: not the reviews of the earlier
    landing, not the repository, not the report store."""
    repository = FakeRepository(
        {
            BASE: with_declaration({RULES: b"x = 1\n"}),
            HEAD: with_declaration({RULES: b"x = 2\n"}),
        },
        history={DECLARATION_PATH: (BASE.revision, EARLIER)},
    )
    reviews = _AskedReviews(FakeReviews({BASE.revision: TimedOut("read the reviews")}))
    store = FakeReportStore()

    report = _walked(repository, reviews, store)

    assert report.verdict is Verdict.INCONCLUSIVE, report.reasons
    assert report.findings == ()
    timed_out = {c.check for c in report.coverage if "timed out" in c.reason}
    assert timed_out >= {c.name for c in CATALOG if c.quality is not Quality.DECLARED}
    assert reviews.asked == [BASE.revision]
    assert repository.asked == [("changed", HEAD), ("history", BASE)]
    assert store.asked == []


def test_judge_change_out_of_time_in_the_walk_asks_no_more_reviews() -> None:
    """Given a CI run whose time ends while the base's CODEOWNERS is read to
    count the newest landing, When the change is judged, Then the reviews
    of the earlier landing are never asked for and the verdict is
    inconclusive, the rest coverage."""
    repository = FakeRepository(
        {
            BASE: with_declaration(
                {RULES: b"x = 1\n", "CODEOWNERS": TimedOut("read CODEOWNERS")}
            ),
            HEAD: with_declaration({RULES: b"x = 2\n"}),
        },
        history={DECLARATION_PATH: (BASE.revision, EARLIER)},
    )
    approved = Landing(author="alice", approvals=(Approval("owner", "d" * 40),))
    reviews = _AskedReviews(FakeReviews({BASE.revision: approved, EARLIER: approved}))
    store = FakeReportStore()

    report = _walked(repository, reviews, store)

    assert report.verdict is Verdict.INCONCLUSIVE, report.reasons
    assert report.findings == ()
    assert any("timed out" in c.reason for c in report.coverage)
    assert reviews.asked == [BASE.revision]
    assert ("tree", HEAD) not in repository.asked
    assert store.asked == []
