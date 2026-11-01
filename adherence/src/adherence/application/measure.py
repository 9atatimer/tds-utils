"""application/measure.py -- measure: one run over one target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism >
Measurement: list the target, read the sources of each measured
language, model them, merge the metrics, read the records, run every
target-level check, and cover whatever could not be read, analyzed or
answered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from adherence.domain.checks.run import run_checks
from adherence.domain.coverage import Coverage, unmeasured, unmodelled
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    exempted,
    refusal_notices,
    with_overrides,
)
from adherence.domain.finding import Finding, quoted
from adherence.domain.model import (
    CodeLanguage,
    CodeModel,
    Metrics,
    MetricsUnavailable,
    language_of,
    merged,
)
from adherence.domain.parameters import Parameters
from adherence.domain.questions import (
    Abstention,
    Ask,
    Decision,
    Judged,
    Pass,
    Rejected,
    Unavailable,
    schemas,
    settled,
    unanswered_checks,
    unasked,
    within_budget,
)
from adherence.domain.records import (
    DesignRecords,
    Radar,
    RecordsUnavailable,
    counted,
)
from adherence.domain.report import (
    JUDGE_UNASKED,
    SUITE_VERSION,
    BodyDigest,
    Report,
    ReportIdentity,
    body_digest,
    fingerprint,
)
from adherence.domain.target import Base, Head
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.repository import Absent, Refused, RepositoryPort

UNDECLARED = RecordsUnavailable("the repository has no declaration to name a record")


@dataclass(frozen=True, slots=True)
class _Read:
    """A language's sources as read, and the paths that could not be."""

    sources: dict[str, bytes]
    coverage: tuple[Coverage, ...]


def _read_sources(
    paths: tuple[str, ...],
    language: CodeLanguage,
    at: Base | Head,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> _Read:
    sources: dict[str, bytes] = {}
    coverage: list[Coverage] = []
    for path in paths:
        if language_of(path) != language.value:
            continue
        data = repository.read(path, at, deadline)
        if isinstance(data, bytes):
            sources[path] = data
        elif isinstance(data, Absent):
            coverage.append(Coverage("listed but absent when read", path=path))
        elif isinstance(data, TimedOut):
            coverage.append(Coverage(f"{data.operation}: timed out", path=path))
        else:
            coverage.append(Coverage(f"cannot be read: {data.reason}", path=path))
    return _Read(sources, tuple(coverage))


def _model(
    read: _Read,
    language: CodeLanguage,
    analyzer: CodeModelPort,
    declaration: Declaration,
    parameters: Parameters,
    deadline: Deadline | None,
) -> CodeModel | tuple[Coverage, ...]:
    model = analyzer.model(read.sources, declaration, parameters.vocabulary, deadline)
    if isinstance(model, CodeModel):
        return model
    reason = f"the {language.value} analyzer: {model.operation}: timed out"
    return tuple(Coverage(reason, path=path) for path in sorted(read.sources))


def _metrics(
    answer: Metrics | MetricsUnavailable | TimedOut, check: str
) -> Metrics | Coverage:
    if isinstance(answer, Metrics):
        return answer
    if isinstance(answer, MetricsUnavailable):
        return Coverage(answer.reason, check=check)
    return Coverage(f"{answer.operation}: timed out", check=check)


def _failed(answer: Unavailable | TimedOut) -> str:
    if isinstance(answer, Unavailable):
        return f"was not asked: the judge is unavailable: {answer.reason}"
    return f"was not asked: {answer.operation}: timed out"


def _judge(
    asks: tuple[Ask, ...],
    judge: DecisionPort,
    parameters: Parameters,
    deadline: Deadline | None,
) -> Judged:
    """Each unit's questions put to the judge in one call, and the answers
    settled by the threshold policy, within the judged-check budget. After
    the judge first fails -- unavailable or out of time -- it is not asked
    again, and every question left is coverage; a call the judge rejects is
    coverage, and the next is still asked."""
    asked, over_budget = within_budget(asks, parameters.limits.judged_budget)
    findings: list[Finding] = []
    passes: list[Pass] = []
    abstentions: list[Abstention] = []
    coverage: list[Coverage] = list(over_budget)
    failure: Unavailable | TimedOut | None = None
    for asking in schemas(asked):
        answer = failure or judge.decide(asking.state, asking.schema, deadline)
        if isinstance(answer, Decision):
            judged = settled(asking, answer, parameters.thresholds)
            findings.extend(judged.findings)
            passes.extend(judged.passes)
            abstentions.extend(judged.abstentions)
            coverage.extend(judged.coverage)
        elif isinstance(answer, Rejected):
            coverage.extend(
                unasked(asking, f"was rejected by the judge: {answer.reason}")
            )
        else:
            failure = answer
            coverage.extend(unasked(asking, _failed(answer)))
    return Judged(tuple(findings), tuple(passes), tuple(abstentions), tuple(coverage))


def measure(
    at: Base | Head,
    declaration: Declaration | DeclarationUnreadable,
    *,
    repository: RepositoryPort,
    analyzers: Mapping[CodeLanguage, CodeModelPort],
    complexity: ComplexityPort,
    duplication: DuplicationPort,
    records: RecordsPort,
    judge: DecisionPort,
    parameters: Parameters,
    deadline: Deadline | None,
) -> Report:
    """The Report of every target-level check over the target."""
    if isinstance(declaration, DeclarationUnreadable):
        return Report.not_run(f"the declaration cannot be read: {declaration.reason}")
    identity = ReportIdentity(
        suite=SUITE_VERSION,
        parameters=fingerprint(parameters),
        declaration=fingerprint(declaration),
        analyzers=tuple(sorted(language.value for language in analyzers)),
        judge=JUDGE_UNASKED,
    )
    parameters = with_overrides(parameters, declaration)
    paths = repository.tree(at, deadline)
    if isinstance(paths, TimedOut):
        return Report.not_run(f"the repository cannot be read: {paths.operation}")
    if isinstance(paths, Refused):
        return Report.not_run(f"the repository cannot be read: {paths.reason}")
    measured = {language.value for language in analyzers}
    if not any(language_of(path) in measured for path in paths):
        # Not run, and still naming every source no analyzer measures.
        return replace(
            Report.not_run(
                "no unit in a measured language "
                f"({', '.join(sorted(measured)) or 'none bound'})"
            ),
            coverage=unmeasured(paths, analyzers.keys()),
        )
    models: list[CodeModel] = []
    sources: dict[str, bytes] = {}
    coverage: list[Coverage] = list(unmeasured(paths, analyzers.keys()))
    for language, analyzer in analyzers.items():
        read = _read_sources(paths, language, at, repository, deadline)
        sources.update(read.sources)
        coverage.extend(read.coverage)
        model = _model(read, language, analyzer, declaration, parameters, deadline)
        if isinstance(model, CodeModel):
            models.append(model)
        else:
            coverage.extend(model)
    unmeasured_checks: set[str] = set()
    for answer in (
        _metrics(complexity.measure(sources, deadline), "Complexity"),
        _metrics(duplication.measure(sources, deadline), "Duplication"),
    ):
        if isinstance(answer, Metrics):
            models.append(CodeModel(metrics=answer))
        else:
            coverage.append(answer)
            unmeasured_checks.add(answer.check or "")
    whole = merged(models)
    design: DesignRecords | RecordsUnavailable = UNDECLARED
    if declaration.declared:
        read_records = records.records(at, declaration, deadline)
        design = (
            RecordsUnavailable(f"{read_records.operation}: timed out")
            if isinstance(read_records, TimedOut)
            else counted(read_records, parameters.limits.record_statuses)
        )
    tech: Radar | RecordsUnavailable = UNDECLARED
    if declaration.declared:
        read_radar = records.radar(at, declaration, deadline)
        tech = (
            RecordsUnavailable(f"{read_radar.operation}: timed out")
            if isinstance(read_radar, TimedOut)
            else read_radar
        )
    checked = run_checks(whole, declaration, design, parameters, radar=tech)
    judged = _judge(checked.questions, judge, parameters, deadline)
    unjudged = unanswered_checks(checked.questions, judged)
    findings, applied = exempted(
        quoted(
            (*checked.findings, *judged.findings),
            sources,
            parameters.limits.evidence_bound,
        ),
        declaration,
    )
    return Report(
        ran=tuple(
            c
            for c in checked.ran
            if c.name not in unmeasured_checks and c.name not in unjudged
        ),
        findings=findings,
        notices=(*refusal_notices(declaration), *applied),
        coverage=(
            *coverage,
            *unmodelled(whole, declaration),
            *checked.coverage,
            *judged.coverage,
        ),
        abstentions=judged.abstentions,
        passes=judged.passes,
        units=whole.units,
        bodies=tuple(
            BodyDigest(d.unit.path, d.unit.symbol, body_digest(d.body.text))
            for d in whole.definitions
            if d.unit.symbol is not None
        ),
        identity=identity,
        revision=at.revision,
    )
