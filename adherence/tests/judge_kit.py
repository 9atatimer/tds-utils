"""Drive `judge_change` by its signature with a fake behind every port.

A test names the files the base and the head hold, the facts the code
model answers with (`when` keys facts to a source's exact bytes, so one
path can carry a flaw at the base and none at the head), and anything
else it scripts; the declaration defaults to the measure kit's hexagon
on both sides, and every other port answers plainly. The declaration's
history defaults to one landing, the base's own, which the fake reviews
answer Unknown, so the base's declaration stands unless a test scripts the
landings and the reviews of them.
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
from adherence.domain.questions import Unavailable
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import Report
from adherence.domain.target import Base, Change, Head
from adherence.ports.repository import Refused
from tests.measure_kit import HEXAGON, declared, parameters

BASE = Base("b" * 40)
HEAD = Head.at_revision("c" * 40)
REPOSITORY = "example"
RULES = "src/app/domain/rules.py"

Files = Mapping[str, bytes | Refused | TimedOut]


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
    reads: list[tuple[str, Base | Head]] | None = None,
) -> Report:
    """judge_change of HEAD against BASE, each holding its files and the
    hexagon declaration unless the files carry their own. `history` lists
    the commits that changed the declaration, newest first; `landed` holds
    the files at commits other than the base and the head. `reads`, when
    given, is extended with every read the repository was asked for."""
    repository = FakeRepository(
        {
            BASE: with_declaration(base),
            HEAD: with_declaration(head),
            **{Base(commit): files for commit, files in (landed or {}).items()},
        },
        unlisted_at=unlisted_at,
        history={DECLARATION_PATH: history},
    )
    report = judge_change(
        Change(REPOSITORY, BASE, HEAD),
        repository=repository,
        reviews=reviews if reviews is not None else FakeReviews(),
        analyzers={
            CodeLanguage.PYTHON: FakeCodeModel(facts=facts or CodeModel(), when=when)
        },
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords(records or {}),
        judge=FakeDecision(Unavailable("no judge in the unit tier")),
        reports=store if store is not None else FakeReportStore(),
        parameters=parameters(),
        deadline=None,
    )
    if reads is not None:
        reads.extend(repository.reads)
    return report


def measured_at(
    files: Files,
    *,
    at: Base | Head = BASE,
    facts: CodeModel | None = None,
    when: Mapping[bytes, CodeModel] | None = None,
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
        judge=FakeDecision(Unavailable("no judge in the unit tier")),
        parameters=parameters(),
        deadline=None,
    )
