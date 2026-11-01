"""Drive `judge_change` by its signature with a fake behind every port.

A test names the files the base and the head hold, the facts the code
model answers with (`when` keys facts to a source's exact bytes, so one
path can carry a flaw at the base and none at the head), and anything
else it scripts; the declaration defaults to the measure kit's hexagon
on both sides, and every other port answers plainly -- the judge passes
every judged question it is asked, so no judged check bears on the
verdict. The declaration's history defaults to one landing, the base's
own, which the fake reviews answer Unknown, so the base's declaration
stands unless a test scripts the landings and the reviews of them.
"""

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
from adherence.application.judge import judge_change
from adherence.application.measure import measure
from adherence.domain.deadline import TimedOut
from adherence.domain.declaration import DECLARATION_PATH
from adherence.domain.model import (
    Body,
    CodeLanguage,
    CodeModel,
    Definition,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Parameters
from adherence.domain.questions import (
    DOES_IO,
    IMPLEMENTED,
    INVARIANT_BROKEN,
    RULES_ELSEWHERE,
    SAME_CONCEPT,
    SCATTERED_POLICY,
    THEN_ASSERTED,
    TWO_JOBS,
    BandThreshold,
    Question,
    ThresholdPolicy,
)
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import Report
from adherence.domain.target import Base, Change, Head
from adherence.ports.decision import DecisionPort
from adherence.ports.repository import Refused
from tests.measure_kit import HEXAGON, declared, parameters

BASE = Base("b" * 40)
HEAD = Head.at_revision("c" * 40)
REPOSITORY = "example"
RULES = "src/app/domain/rules.py"

Files = Mapping[str, bytes | Refused | TimedOut]

# Every binary and score question; Hand-rolled is not asked with no radar.
BANDED: tuple[Question, ...] = (
    TWO_JOBS,
    DOES_IO,
    SAME_CONCEPT,
    SCATTERED_POLICY,
    INVARIANT_BROKEN,
    RULES_ELSEWHERE,
    THEN_ASSERTED,
    IMPLEMENTED,
)


def _passed(question: Question) -> dict[str, float]:
    """No probability on a failing answer, the rest spread evenly."""
    kept = [o for o in question.options if o not in question.failing]
    return {o: (1.0 / len(kept) if o in kept else 0.0) for o in question.options}


def passing_judge() -> FakeDecision:
    """A judge that passes every binary and score question."""
    return FakeDecision({q.id: _passed(q) for q in BANDED})


def answering(question: Question, probabilities: Mapping[str, float]) -> FakeDecision:
    """The passing judge, but answering one question with the probabilities
    given."""
    return FakeDecision(
        {**{q.id: _passed(q) for q in BANDED}, question.id: probabilities}
    )


def judged_parameters() -> Parameters:
    """The measure kit's parameters with a band for every question the
    passing judge answers, so each answer settles as a pass."""
    band = BandThreshold(finding_at=0.8, pass_below=0.3)
    return parameters(thresholds=ThresholdPolicy({q.id: band for q in BANDED}))


def stubbed(
    path: str, symbol: str, line: int, *, stub: str | None = "pass"
) -> CodeModel:
    """The facts of one function from `line` (its def) to the line after:
    its body the stub marker, or working code when `stub` is None."""
    unit = Unit(path, UnitKind.FUNCTION, symbol, line, line + 1, None)
    body = Body(stub, (stub,), ()) if stub else Body("return 1", (), ())
    return CodeModel(
        units=(unit,),
        definitions=(Definition(unit, None, body, (), (), None, False),),
    )


def with_declaration(
    files: Files, declaration: bytes = HEXAGON
) -> dict[str, bytes | Refused | TimedOut]:
    """The files with the declaration added, unless they name their own."""
    return {DECLARATION_PATH: declaration, **files}


def judge_with(
    base: Files,
    head: Files,
    *,
    facts: CodeModel | None = None,
    when: Mapping[bytes, CodeModel] | None = None,
    records: Mapping[Base | Head, DesignRecords | RecordsUnavailable | TimedOut]
    | None = None,
    store: FakeReportStore | None = None,
    unlisted_at: Mapping[Base | Head, Refused | TimedOut] | None = None,
    history: tuple[str, ...] | Refused | TimedOut = (BASE.revision,),
    reviews: FakeReviews | None = None,
    landed: Mapping[str, Files] | None = None,
    judge: DecisionPort | None = None,
) -> Report:
    """judge_change of HEAD against BASE, each holding its files and the
    hexagon declaration unless the files carry their own; the judge is the
    passing one unless the test binds another. `history` lists the commits
    that changed the declaration, newest first; `landed` holds the files at
    commits other than the base and the head."""
    return judge_change(
        Change(REPOSITORY, BASE, HEAD),
        repository=FakeRepository(
            {
                BASE: with_declaration(base),
                HEAD: with_declaration(head),
                **{Base(commit): files for commit, files in (landed or {}).items()},
            },
            unlisted_at=unlisted_at,
            history={DECLARATION_PATH: history},
        ),
        reviews=reviews if reviews is not None else FakeReviews(),
        analyzers={
            CodeLanguage.PYTHON: FakeCodeModel(facts=facts or CodeModel(), when=when)
        },
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords(records or {}),
        judge=judge if judge is not None else passing_judge(),
        reports=store if store is not None else FakeReportStore(),
        parameters=judged_parameters(),
        deadline=None,
    )


def measured_at(
    files: Files,
    *,
    at: Base | Head = BASE,
    facts: CodeModel | None = None,
    when: Mapping[bytes, CodeModel] | None = None,
    judge: DecisionPort | None = None,
) -> Report:
    """measure of one target holding the files, under the hexagon, with the
    ports judge_with binds: the report an earlier run would have kept."""
    return measure(
        at,
        declared(),
        repository=FakeRepository({at: with_declaration(files)}),
        analyzers={
            CodeLanguage.PYTHON: FakeCodeModel(facts=facts or CodeModel(), when=when)
        },
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords({}),
        judge=judge if judge is not None else passing_judge(),
        parameters=judged_parameters(),
        deadline=None,
    )
