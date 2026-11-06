"""application/measure.py -- measure: one run over one target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism >
Measurement: list the target, read the sources of each measured
language, model them, merge the metrics, read the records, run every
target-level check, and cover whatever could not be read, analyzed or
answered.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from adherence.application.latch import (
    Latch,
    LatchedComplexity,
    LatchedDecision,
    LatchedDuplication,
    LatchedRecords,
    LatchedRepository,
    latched_analyzers,
)
from adherence.domain.checks.run import each_check, gathered
from adherence.domain.coverage import (
    Coverage,
    unmeasured,
    unmeasured_in,
    unmodelled,
    unread_script,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    exempted,
    refusal_notices,
    with_overrides,
)
from adherence.domain.finding import Finding, Notice, quoted
from adherence.domain.model import (
    CodeLanguage,
    CodeModel,
    Metrics,
    MetricsUnavailable,
    has_no_extension,
    language_of,
    merged,
    script_language,
    with_languages,
)
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG, Quality
from adherence.domain.questions import (
    Abstention,
    Ask,
    Availability,
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
)
from adherence.domain.report import (
    SUITE_VERSION,
    BodyDigest,
    FinishedCheck,
    Report,
    ReportIdentity,
    RunCoverage,
    RunNotices,
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
from adherence.ports.worker import FinishedSink

UNDECLARED = RecordsUnavailable("the repository has no declaration to name a record")


@dataclass(frozen=True, slots=True)
class _Read:
    """A language's sources as read, and the paths that could not be."""

    sources: dict[str, bytes]
    coverage: tuple[Coverage, ...]


@dataclass(frozen=True, slots=True)
class _Scripts:
    """The shell scripts found by shebang among files with no extension,
    read, and the coverage for every other one found or not read."""

    shell: dict[str, bytes]
    coverage: tuple[Coverage, ...]


def _read_scripts(
    paths: tuple[str, ...],
    at: Base | Head,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> _Scripts:
    """Each file with no extension, read for its shebang (Issue#638). A file
    that is refused or cut off by the deadline could be a script, so it is
    coverage with why; one gone by the time it is read is not."""
    shell: dict[str, bytes] = {}
    coverage: list[Coverage] = []
    for path in paths:
        if not has_no_extension(path):
            continue
        data = repository.read(path, at, deadline)
        if isinstance(data, TimedOut):
            coverage.append(Coverage(f"{data.operation}: timed out", path=path))
            continue
        if isinstance(data, Refused):
            coverage.append(Coverage(f"cannot be read: {data.reason}", path=path))
            continue
        if not isinstance(data, bytes):
            continue
        language = script_language(data)
        if language == CodeLanguage.SHELL.value:
            shell[path] = data
        elif language is not None:
            coverage.append(unread_script(language, path))
    return _Scripts(shell, tuple(coverage))


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
) -> tuple[Judged, Availability]:
    """Each unit's questions put to the judge in one call, and the answers
    settled by the threshold policy, within the judged-check budget, with
    the judge's availability: the bound judge's, unless it could not be
    reached. The budget is a bound judge's: with none bound, the port is
    asked once for why, and every question is coverage naming that, never
    the budget. After the judge first fails -- unavailable or out of time
    -- it is not asked again, and every question left is coverage; a call
    the judge rejects is coverage, and the next is still asked."""
    bound = judge.availability() is Availability.AVAILABLE
    budget = parameters.limits.judged_budget if bound else len(asks)
    asked, over_budget = within_budget(asks, budget)
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
    availability = (
        Availability.UNAVAILABLE
        if isinstance(failure, Unavailable)
        else judge.availability()
    )
    judged = Judged(tuple(findings), tuple(passes), tuple(abstentions), tuple(coverage))
    return judged, availability


def reported(
    found: Iterable[Coverage], finished: FinishedSink | None
) -> tuple[Coverage, ...]:
    """Run-level coverage as it is found, reported to `finished` at once, so
    a run ended later -- inside an analyzer, say -- still names it."""
    items = tuple(found)
    if finished is not None and items:
        finished(RunCoverage(items))
    return items


def noticed(found: Iterable[Notice], finished: FinishedSink | None) -> None:
    """Run-level notices as they are known, reported to `finished` at once,
    so a run ended later still says them."""
    items = tuple(found)
    if finished is not None and items:
        finished(RunNotices(items))


def _with_judged(check: FinishedCheck, judged: Judged) -> FinishedCheck:
    """A check that asked the judge, with what the judge's answers made of
    its questions: its judged findings, passes, abstentions and the
    questions left unanswered."""
    name = check.check.name
    return replace(
        check,
        findings=(
            *check.findings,
            *(f for f in judged.findings if f.check == check.check),
        ),
        coverage=(*check.coverage, *(c for c in judged.coverage if c.check == name)),
        passes=tuple(p for p in judged.passes if p.check == check.check),
        abstentions=tuple(a for a in judged.abstentions if a.check == check.check),
        questions=(),
    )


def _as_reported(
    check: FinishedCheck,
    sources: Mapping[str, bytes],
    declaration: Declaration,
    parameters: Parameters,
    unmeasured: set[str] | frozenset[str],
) -> tuple[FinishedCheck, tuple[Notice, ...]]:
    """A finished check as the Report shows it: evidence quoted within the
    bound, exemptions applied, and not run when its metrics were not; and
    the notice of each exemption applied."""
    findings, applied = exempted(
        quoted(check.findings, sources, parameters.limits.evidence_bound),
        declaration,
    )
    ran = check.ran and check.check.name not in unmeasured
    return replace(check, findings=findings, ran=ran), applied


def measure_reporting(
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
    finished: FinishedSink | None,
) -> Report:
    """measure, reporting each check to `finished` as it finishes, its
    evidence quoted and its exemptions applied as the Report will have
    them, and each notice as soon as it is known: the job judge_bounded
    runs reports the head's checks this way."""
    if isinstance(declaration, DeclarationUnreadable):
        return Report.not_run(f"the declaration cannot be read: {declaration.reason}")
    noticed(refusal_notices(declaration), finished)
    latch = Latch()
    repository = LatchedRepository(repository, latch)
    analyzers = latched_analyzers(analyzers, latch)
    complexity = LatchedComplexity(complexity, latch)
    duplication = LatchedDuplication(duplication, latch)
    records = LatchedRecords(records, latch)
    judge = LatchedDecision(judge, latch)
    identity = ReportIdentity(
        suite=SUITE_VERSION,
        parameters=fingerprint(parameters),
        declaration=fingerprint(declaration),
        analyzers=tuple(sorted(language.value for language in analyzers)),
        judge=judge.availability().value,
    )
    parameters = with_overrides(parameters, declaration)
    paths = repository.tree(at, deadline)
    if isinstance(paths, TimedOut):
        # Cut off, not unable to run: every check is coverage.
        reason = f"{paths.operation}: timed out"
        return Report(
            coverage=tuple(
                Coverage(reason, check=c.name)
                for c in CATALOG
                if c.quality is not Quality.DECLARED
            ),
            identity=identity,
            revision=at.revision,
        )
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
    coverage = list(reported(unmeasured(paths, analyzers.keys()), finished))
    scripts = _read_scripts(paths, at, repository, deadline)
    coverage.extend(reported(scripts.coverage, finished))
    if CodeLanguage.SHELL not in analyzers:
        shell = CodeLanguage.SHELL.value
        coverage.extend(
            reported(
                (unmeasured_in(shell, path) for path in sorted(scripts.shell)),
                finished,
            )
        )
    for language, analyzer in analyzers.items():
        read = _read_sources(paths, language, at, repository, deadline)
        if language is CodeLanguage.SHELL:
            read = _Read({**read.sources, **scripts.shell}, read.coverage)
        sources.update(read.sources)
        coverage.extend(reported(read.coverage, finished))
        model = _model(read, language, analyzer, declaration, parameters, deadline)
        if isinstance(model, CodeModel):
            models.append(model)
        else:
            coverage.extend(reported(model, finished))
    unmeasured_checks: set[str] = set()
    for answer in (
        _metrics(complexity.measure(sources, deadline), "Complexity"),
        _metrics(duplication.measure(sources, deadline), "Duplication"),
    ):
        if isinstance(answer, Metrics):
            models.append(CodeModel(metrics=answer))
        else:
            coverage.extend(reported((answer,), finished))
            unmeasured_checks.add(answer.check or "")
    whole = with_languages(
        merged(models), {path: CodeLanguage.SHELL.value for path in scripts.shell}
    )
    design: DesignRecords | RecordsUnavailable = UNDECLARED
    if declaration.declared:
        read_records = records.records(at, declaration, deadline)
        design = (
            RecordsUnavailable(f"{read_records.operation}: timed out")
            if isinstance(read_records, TimedOut)
            else read_records
        )
    tech: Radar | RecordsUnavailable = UNDECLARED
    if declaration.declared:
        read_radar = records.radar(at, declaration, deadline)
        tech = (
            RecordsUnavailable(f"{read_radar.operation}: timed out")
            if isinstance(read_radar, TimedOut)
            else read_radar
        )
    reported(unmodelled(whole, declaration), finished)
    done: list[FinishedCheck] = []
    for check in each_check(whole, declaration, design, parameters, radar=tech):
        done.append(check)
        if finished is not None and not check.questions:
            shown, applied = _as_reported(
                check, sources, declaration, parameters, unmeasured_checks
            )
            noticed(applied, finished)
            finished(shown)
    checked = gathered(tuple(done))
    judged, availability = _judge(checked.questions, judge, parameters, deadline)
    unjudged = unanswered_checks(checked.questions, judged)
    if finished is not None:
        # A check that asked the judge finishes once the judge has answered.
        for check in done:
            if check.questions:
                shown, applied = _as_reported(
                    _with_judged(check, judged),
                    sources,
                    declaration,
                    parameters,
                    unmeasured_checks | unjudged,
                )
                noticed(applied, finished)
                finished(shown)
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
        identity=replace(identity, judge=availability.value),
        revision=at.revision,
    )


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
    """The Report of every target-level check over the target. Once any
    port answers TimedOut, no port is asked anything more: what is left is
    coverage."""
    return measure_reporting(
        at,
        declaration,
        repository=repository,
        analyzers=analyzers,
        complexity=complexity,
        duplication=duplication,
        records=records,
        judge=judge,
        parameters=parameters,
        deadline=deadline,
        finished=None,
    )
