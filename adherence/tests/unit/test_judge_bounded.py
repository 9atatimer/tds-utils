"""The hook ends within its bound (DESIGN.ARCH-ADHERENCE.md, Behaviors;
ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface): judge_bounded driven by
its signature, with inline_worker scripted to end the job after one check
and a fake behind every other port."""

from __future__ import annotations

from collections.abc import Mapping

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
from adherence.adapters.inline_worker import FakeWorker
from adherence.application.bounded import judge_bounded
from adherence.application.judge import judge_change
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import DECLARATION_PATH
from adherence.domain.model import CodeLanguage, Metrics, MetricsUnavailable
from adherence.domain.qualities import CATALOG
from adherence.domain.questions import Unavailable
from adherence.domain.report import ENDED, Report, Verdict
from adherence.domain.target import Change
from adherence.ports.complexity import ComplexityPort
from adherence.ports.repository import Refused
from adherence.ports.worker import WorkerPort
from tests.judge_kit import (
    BASE,
    HEAD,
    REPOSITORY,
    RULES,
    stubbed,
    with_declaration,
)
from tests.measure_kit import HEXAGON, parameters

# The commit-time bound, as an instant no fake's frozen clock has reached.
HOOK_DEADLINE = Deadline(epoch_seconds=2e9)
CHANGE = Change(REPOSITORY, BASE, HEAD)
BROKE = "the complexity tooling broke"
SECRET = "src/app/domain/secret.py"
# The declaration's one landing, the base's own, which the fake reviews
# answer Unknown, so the base's declaration stands (tests/judge_kit.py).
LANDED = {DECLARATION_PATH: (BASE.revision,)}


class _BrokenComplexity:
    """ComplexityPort whose tooling raises: an engine that failed."""

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        raise RuntimeError(BROKE)


def _repository() -> FakeRepository:
    return FakeRepository(
        {
            BASE: with_declaration({RULES: b"x = 1\n"}),
            HEAD: with_declaration({RULES: b"x = 2\n"}),
        },
        history=LANDED,
    )


def _bounded(
    worker: WorkerPort,
    repository: FakeRepository,
    store: FakeReportStore,
    complexity: ComplexityPort | None = None,
    analyzer: FakeCodeModel | None = None,
) -> Report:
    return judge_bounded(
        CHANGE,
        worker=worker,
        deadline=HOOK_DEADLINE,
        repository=repository,
        reviews=FakeReviews(),
        analyzers={
            CodeLanguage.PYTHON: analyzer if analyzer is not None else FakeCodeModel()
        },
        complexity=complexity if complexity is not None else FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords({}),
        judge=FakeDecision(Unavailable("no judge in the hook")),
        reports=store,
        parameters=parameters(),
    )


def test_judge_bounded_ended_after_one_check_covers_the_rest() -> None:
    """Given a staged change and a worker that ends the job after one check,
    When the hook judges it, Then the run ends there, every check that did
    not finish is coverage, the verdict is inconclusive, and no port is
    asked anything after."""
    repository = _repository()
    store = FakeReportStore()

    report = _bounded(FakeWorker(ends_after=1), repository, store)

    assert report.verdict is Verdict.INCONCLUSIVE
    ended = {c.check for c in report.coverage if c.reason == ENDED}
    assert ended == {c.name for c in CATALOG[1:]}
    assert CATALOG[0].name not in ended
    assert store.asked == []
    assert ("tree", BASE) not in repository.asked


def test_judge_bounded_whose_job_finishes_is_judge_changes_report() -> None:
    """Given a worker that lets the job finish, When the hook judges the
    change, Then the report is the one judge_change gives, verdict and all."""
    report = _bounded(FakeWorker(), _repository(), FakeReportStore())

    assert report == judge_change(
        CHANGE,
        repository=_repository(),
        reviews=FakeReviews(),
        analyzers={CodeLanguage.PYTHON: FakeCodeModel()},
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords({}),
        judge=FakeDecision(Unavailable("no judge in the hook")),
        reports=FakeReportStore(),
        parameters=parameters(),
        deadline=HOOK_DEADLINE,
    )


def test_judge_bounded_whose_engine_fails_is_not_run() -> None:
    """Given a staged change and an engine that fails while it measures,
    When the hook judges it, Then the suite could not measure: the verdict
    is not run with the failure as its reason -- never inconclusive, which
    is the deadline's -- and nothing reads as a pass."""
    report = _bounded(
        FakeWorker(), _repository(), FakeReportStore(), _BrokenComplexity()
    )

    assert report.verdict is Verdict.NOT_RUN, report.reasons
    assert any(BROKE in r for r in report.reasons)
    assert report.ran == () and report.findings == ()
    assert not any(c.reason == ENDED for c in report.coverage)


def test_judge_bounded_ended_keeps_a_file_it_could_not_read() -> None:
    """Given a staged change with a file in a measured language that cannot
    be read at the head, and a worker that ends the job once a check has
    finished, When the hook judges it, Then coverage still names the file
    (DESIGN.ARCH-ADHERENCE.md, An unreadable file is coverage) beside the
    checks that did not finish."""
    repository = FakeRepository(
        {
            BASE: with_declaration({RULES: b"x = 1\n"}),
            HEAD: with_declaration(
                {RULES: b"x = 2\n", SECRET: Refused(SECRET, "a symbolic link")}
            ),
        },
        history=LANDED,
    )

    report = _bounded(FakeWorker(ends_after=1), repository, FakeReportStore())

    assert report.verdict is Verdict.INCONCLUSIVE
    assert any(
        c.path == SECRET and "a symbolic link" in c.reason for c in report.coverage
    ), report.coverage


# Refuses an exemption of a declared check, and applies one to the stub.
NOTICED = HEXAGON + (
    b'\n[[exemptions]]\ncheck = "Covered"\nunit = "src/app/new.py"\nreason = "r"\n'
    b'\n[[exemptions]]\ncheck = "Stub"\nunit = "src/app/domain/rules.py"\n'
    b'reason = "kept until the rewrite"\n'
)
STUBBED = b"def rule():\n    pass\n"


def test_judge_bounded_ended_keeps_the_notices_reported_before_the_end() -> None:
    """Given a declaration that states a refused exemption and one that
    silences a stub, and a worker that ends the job once the Stub check has
    finished, When the hook judges the change, Then the partial report
    still carries the refusal notice and the applied-exemption notice."""
    repository = FakeRepository(
        {
            BASE: with_declaration({RULES: b"x = 1\n"}, NOTICED),
            HEAD: with_declaration({RULES: STUBBED}, NOTICED),
        },
        history=LANDED,
    )
    stub_index = [c.name for c in CATALOG].index("Stub")
    analyzer = FakeCodeModel(when={STUBBED: stubbed(RULES, "rule", 1)})

    report = _bounded(
        FakeWorker(ends_after=stub_index + 1),
        repository,
        FakeReportStore(),
        analyzer=analyzer,
    )

    assert report.verdict is Verdict.INCONCLUSIVE
    assert "Stub" not in {c.check for c in report.coverage if c.reason == ENDED}
    messages = [n.message for n in report.notices]
    assert any("refused" in m and "src/app/new.py" in m for m in messages), messages
    assert any(
        "exemption applied" in m and "kept until the rewrite" in m for m in messages
    ), messages
